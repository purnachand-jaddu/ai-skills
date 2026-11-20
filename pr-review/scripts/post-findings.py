#!/usr/bin/env python3
"""Post a review on a GitLab MR or GitHub PR: a summary note led by the verdict, then one line comment per finding on its added line, else a general comment.

post-findings.py <mr-or-pr-url> <findings.json> --verdict "<report's first line>" --reviewed <sha> --model M --provider P --harness H [--dry-run]
findings.json: [{"severity": "Should fix", "title": "...", "path": "a/b.go", "line": 42, "body": "markdown"}]
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from urllib.parse import quote, urlparse

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def run(cmd, stdin=None):
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"{' '.join(cmd[:4])}: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout


def added_lines(diff):
    """New-side line numbers of the '+' lines in a unified diff."""
    out, new = set(), 0
    for ln in (diff or "").splitlines():
        m = HUNK.match(ln)
        if m:
            new = int(m.group(1))
        elif ln.startswith("+"):
            out.add(new)
            new += 1
        elif ln.startswith(" ") or ln == "":
            new += 1
    return out


class GitLab:
    def __init__(self, url):
        u = urlparse(url)
        path, iid = re.match(r"/(.+?)/-/merge_requests/(\d+)", u.path).groups()
        self.host, self.base = u.hostname, f"projects/{quote(path, safe='')}/merge_requests/{iid}"
        self.pid = quote(path, safe="")

    def api(self, path, body=None, paginate=False):
        cmd = ["glab", "api", "--hostname", self.host, path] + (["--paginate", "--output", "ndjson"] if paginate else [])
        if body is not None:
            cmd += ["-X", "POST", "-H", "Content-Type: application/json", "--input", "-"]
        out = run(cmd, None if body is None else json.dumps(body))
        return [json.loads(ln) for ln in out.splitlines() if ln.strip()] if paginate else json.loads(out)

    def head(self):
        self.refs = self.api(self.base)["diff_refs"]
        return self.refs["head_sha"]

    def added(self):
        return {d["new_path"]: (d["old_path"], added_lines(d.get("diff"))) for d in self.api(f"{self.base}/diffs?per_page=100", paginate=True)}

    def raw(self, path, sha):
        return run(["glab", "api", "--hostname", self.host, f"projects/{self.pid}/repository/files/{quote(path, safe='')}/raw?ref={sha}"])

    def bodies(self):
        return [n["body"] for d in self.api(f"{self.base}/discussions?per_page=100", paginate=True) for n in d["notes"]]

    def post_line(self, body, path, old_path, line):
        # A JSON body: glab's -F "position[new_line]=" does not nest, and GitLab then silently posts a general comment.
        pos = {"position_type": "text", **{k: self.refs[k] for k in ("base_sha", "start_sha", "head_sha")},
               "new_path": path, "old_path": old_path, "new_line": line}
        note = self.api(f"{self.base}/discussions", {"body": body, "position": pos})["notes"][0]
        if not (note.get("position") or {}).get("new_path"):
            raise RuntimeError(f"posted as a general comment, not on {path}:{line} (note {note['id']})")
        return f"note {note['id']}"

    def post_general(self, body):
        return f"note {self.api(f'{self.base}/discussions', {'body': body})['notes'][0]['id']}"


class GitHub:
    def __init__(self, url):
        u = urlparse(url)
        repo, n = re.match(r"/([^/]+/[^/]+)/pull/(\d+)", u.path).groups()
        self.host, self.repo, self.n = u.hostname, repo, n

    def api(self, path, body=None, paginate=False):
        cmd = ["gh", "api", "--hostname", self.host, path] + (["--paginate", "--slurp"] if paginate else [])
        if body is not None:
            cmd += ["-X", "POST", "--input", "-"]
        out = json.loads(run(cmd, None if body is None else json.dumps(body)))
        return [x for page in out for x in page] if paginate else out

    def head(self):
        self.sha = self.api(f"repos/{self.repo}/pulls/{self.n}")["head"]["sha"]
        return self.sha

    def added(self):
        return {f["filename"]: (f.get("previous_filename", f["filename"]), added_lines(f.get("patch")))
                for f in self.api(f"repos/{self.repo}/pulls/{self.n}/files?per_page=100", paginate=True)}

    def raw(self, path, sha):
        return run(["gh", "api", "--hostname", self.host, "-H", "Accept: application/vnd.github.raw",
                    f"repos/{self.repo}/contents/{quote(path)}?ref={sha}"])

    def bodies(self):
        return [c["body"] for kind in ("pulls", "issues")
                for c in self.api(f"repos/{self.repo}/{kind}/{self.n}/comments?per_page=100", paginate=True)]

    def post_line(self, body, path, old_path, line):
        c = self.api(f"repos/{self.repo}/pulls/{self.n}/comments",
                     {"body": body, "commit_id": self.sha, "path": path, "line": line, "side": "RIGHT"})
        if c.get("path") != path:
            raise RuntimeError(f"comment {c.get('id')} is not on {path}:{line}")
        return c["html_url"]

    def post_general(self, body):
        return self.api(f"repos/{self.repo}/issues/{self.n}/comments", {"body": body})["html_url"]


def anchor(forge, f, reviewed, head, added):
    """The added line at head that carries the finding's cited line, or None."""
    path, line = f.get("path"), f.get("line")
    if not path or not line or path not in added:
        return None
    if not head.startswith(reviewed):
        try:
            was = forge.raw(path, reviewed).splitlines()[line - 1]
            now = forge.raw(path, head).splitlines()
        except (RuntimeError, IndexError):
            return None
        if line > len(now) or now[line - 1] != was:
            hits = [i + 1 for i, t in enumerate(now) if t == was]
            line = hits[0] if len(hits) == 1 else None
    return line if line in added[path][1] else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("findings")
    for a in ("--verdict", "--reviewed", "--model", "--provider", "--harness"):
        ap.add_argument(a, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.verdict.startswith(("Do not merge:", "Merge after fixes:", "Mergeable:")):
        sys.exit("--verdict must start with 'Do not merge:', 'Merge after fixes:' or 'Mergeable:'")

    forge = GitLab(a.url) if "/-/merge_requests/" in a.url else GitHub(a.url)
    findings = json.load(open(a.findings))
    head = forge.head()
    added = forge.added()
    posted = "\n".join(forge.bodies())
    at = f"verified at `{a.reviewed[:8]}`" + ("" if head.startswith(a.reviewed) else f", cited lines checked at `{head[:8]}`")
    header = f"**Agent review** — {a.model} ({a.provider}), via {a.harness} · diff-review, {at}"
    failed = 0
    label, _, why = a.verdict.partition(":")
    items = "".join(f"\n- {f['severity']}: {f['title']}" + (f" (`{f['path']}:{f.get('line')}`)" if f.get("path") else "") for f in findings)
    summary = {"summary": True, "body": f"{header}\n\n**{label}**:{why}\n{items}\n\n<!-- agent-review:summary:{a.reviewed[:12]} -->"}
    for f in [summary] + findings:
        if f.get("summary"):
            if f["body"].rsplit("\n", 1)[1] in posted:
                print("skipped   summary: already posted")
            elif a.dry_run:
                print("summary\n" + "\n".join("    " + ln for ln in f["body"].splitlines()))
            else:
                try:
                    print(f"summary   {forge.post_general(f['body'])}")
                except RuntimeError as e:
                    failed = 1
                    print(f"failed    summary: {e}")
            continue
        key = hashlib.sha1(f"{f.get('path')}\n{f['title']}".encode()).hexdigest()[:12]
        marker = f"<!-- agent-review:{key} -->"
        where = f"{f['path']}:{f.get('line')}" if f.get("path") else "(no file)"
        if marker in posted:
            print(f"skipped   {where}: already posted")
            continue
        line = anchor(forge, f, a.reviewed, head, added)
        cite = "" if line else (f"\nOn `{where}`, which is not an added line in this diff.\n" if f.get("path") else "")
        body = f"{header}\n\n**{f['severity']}: {f['title']}**\n{cite}{f['body']}\n\n{marker}"
        label = f"line      {f['path']}:{line}" if line else f"general   {where}"
        if a.dry_run:
            print(label + "\n" + "\n".join("    " + ln for ln in body.splitlines()))
            continue
        try:
            ref = forge.post_line(body, f["path"], added[f["path"]][0], line) if line else forge.post_general(body)
            print(f"{label} {ref}")
        except RuntimeError as e:
            failed = 1
            print(f"failed    {where}: {e}")
    sys.exit(failed)


if __name__ == "__main__":
    main()
