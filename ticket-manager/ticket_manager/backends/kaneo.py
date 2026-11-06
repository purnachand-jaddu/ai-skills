import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from ..interface import TicketBackend, TicketError

KEYCHAIN_SERVICE = "kaneo-api-key"
USER_AGENT = "ticket-manager/1.0"  # Cloudflare 1010 blocks the urllib default


def keychain_account() -> str:
    return os.environ.get("USER", "kaneo")


def keychain(*args: str):
    """Run macOS `security`; machines without it must set KANEO_API_KEY."""
    try:
        return subprocess.run(["security", *args], capture_output=True, text=True)
    except FileNotFoundError as err:
        raise TicketError("no Kaneo API key: set KANEO_API_KEY (this machine has no keychain)") from err


def api_key() -> str:
    """KANEO_API_KEY, else the keychain, else ask once (hidden) and cache it in the keychain."""
    if os.environ.get("KANEO_API_KEY"):
        return os.environ["KANEO_API_KEY"]
    found = keychain("find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", keychain_account(), "-w")
    if found.returncode == 0 and found.stdout.strip():
        return found.stdout.strip()
    asked = subprocess.run(["osascript", "-e",
                            'text returned of (display dialog "Kaneo API key (Settings → Account → API Keys)" '
                            'default answer "" with hidden answer with title "ticket-manager")'],
                           capture_output=True, text=True)
    key = asked.stdout.strip()
    if asked.returncode != 0 or not key:
        raise TicketError("no Kaneo API key: set KANEO_API_KEY, or answer the prompt")
    keychain("add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", keychain_account(), "-w", key)
    return key


def reset_key() -> None:
    """Forget the cached key; the next call asks again."""
    keychain("delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", keychain_account())


def http(method: str, url: str, headers: dict, body: bytes | None):
    """One HTTP request; (status, headers, body text)."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read().decode()
    except urllib.error.URLError as err:
        raise TicketError(f"Kaneo unreachable at {url}: {err.reason}") from err


class KaneoBackend(TicketBackend):
    """Kaneo's REST API with an API key (Authorization: Bearer)."""

    name = "kaneo"

    def __init__(self, base_url: str, workspace_id: str, workspace_slug: str, key=api_key, transport=http):
        self.base_url = base_url.rstrip("/")
        self.workspace_id = workspace_id
        self.workspace_slug = workspace_slug
        self.key = key
        self.transport = transport

    def ticket_url(self, key):
        """The ticket's page in the Kaneo web app."""
        return f"{self.base_url.removesuffix('/api')}/{self.workspace_slug}/task/{key}"

    def request(self, method, path, query=None, body=None):
        url = self.base_url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = {"Authorization": f"Bearer {self.key()}", "Accept": "application/json", "User-Agent": USER_AGENT}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, resp_headers, text = self.transport(method, url, headers, data)
        if status == 401:
            raise TicketError("Kaneo rejected the API key (401); run `tm reset-key` and try again")
        if status == 429:
            wait = resp_headers.get("Retry-After", "?")
            raise TicketError(f"Kaneo rate limit (100 requests per 60 s per key); retry after {wait} s")
        if status == 404:
            raise TicketError(f"not found in Kaneo: {method} {path}")
        if status >= 400:
            raise TicketError(f"Kaneo {method} {path} failed ({status}): {text[:300]}")
        return json.loads(text) if text.strip() else {}

    def get(self, key):
        task = self.request("GET", f"/task/by-ticket-id/{key}", {"workspaceId": self.workspace_id})
        return {"id": task["id"], "key": key.upper(), "title": task.get("title"),
                "description": task.get("description") or "",
                "status": task.get("status"), "project_id": task.get("projectId"),
                "url": self.ticket_url(key.upper())}

    def search(self, query, limit):
        found = self.request("GET", "/search", {"q": query, "type": "tasks",
                                                 "workspaceId": self.workspace_id, "limit": limit})
        return [{"id": r["id"], "key": (key := f"{r['projectSlug'].upper()}-{r['taskNumber']}"),
                 "title": r.get("title"), "status": r.get("status"), "project_id": r.get("projectId"),
                 "url": self.ticket_url(key)}
                for r in found.get("results", []) if r.get("type", "task") == "task"]

    def projects(self):
        listed = self.request("GET", "/project", {"workspaceId": self.workspace_id})
        return [{"id": p["id"], "slug": p.get("slug"), "name": p.get("name")} for p in listed]

    def columns(self, project_id):
        cols = self.request("GET", f"/column/{project_id}")
        return [{"slug": c["slug"], "name": c.get("name"), "is_final": bool(c.get("isFinal"))}
                for c in sorted(cols, key=lambda c: c.get("position", 0))]

    def move(self, ticket_id, status):
        self.request("PUT", f"/task/status/{ticket_id}", body={"status": status})

    def comment(self, ticket_id, text):
        self.request("POST", f"/comment/{ticket_id}", body={"content": text})

    def list(self, project_id, status):
        tickets, page, pages = [], 1, 1
        while page <= pages:
            query = {"page": page, "limit": 100, **({"status": status} if status else {})}
            board = self.request("GET", f"/task/tasks/{project_id}", query)
            pages = board.get("pagination", {}).get("totalPages", 1)
            data = board.get("data", {})
            slug = (data.get("slug") or "").upper()
            for column in data.get("columns", []):
                for t in column.get("tasks", []):
                    key = f"{slug}-{t.get('number')}"
                    tickets.append({"id": t["id"], "key": key, "url": self.ticket_url(key), "title": t.get("title"),
                                    "description": t.get("description") or "",
                                    "status": t.get("status"), "priority": t.get("priority"),
                                    "assignee": t.get("assigneeName"), "created_at": t.get("createdAt")})
            page += 1
        return tickets

    def history(self, ticket_id):
        comments = self.request("GET", f"/comment/{ticket_id}")
        activity = self.request("GET", f"/activity/{ticket_id}", {"limit": 100})
        events = [{"at": c.get("createdAt"), "by": c.get("userName") or c.get("userId"), "kind": "comment",
                   "text": c.get("content")} for c in comments]
        events += [{"at": a.get("createdAt"), "by": a.get("externalUserName") or a.get("userId"),
                    "kind": a.get("type"), "text": a.get("content")} for a in activity]
        return sorted(events, key=lambda e: e["at"] or "")

    def relations(self, ticket_id):
        return [{"kind": r.get("relationType"), "source_id": r.get("sourceTaskId"), "target_id": r.get("targetTaskId")}
                for r in self.request("GET", f"/task-relation/{ticket_id}")]

    def labels(self, ticket_id):
        return [label.get("name") for label in self.request("GET", f"/label/task/{ticket_id}")]

    def create(self, project_id, title, description):
        task = self.request("POST", f"/task/{project_id}", body={
            "title": title, "description": description, "priority": "no-priority", "status": "to-do"})
        slug = self.request("GET", f"/project/{project_id}").get("slug", "")
        key = f"{slug.upper()}-{task.get('number')}"
        return {"id": task["id"], "key": key, "title": task.get("title"),
                "status": task.get("status"), "project_id": project_id, "url": self.ticket_url(key)}
