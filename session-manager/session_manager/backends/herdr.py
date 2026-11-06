import json
import os
import shutil
import subprocess
import time

from .. import core
from ..interface import SessionBackend, SessionError

SPINNERS = set("◐◓◑◒⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏✶✻✽✢·")
IDLE = "✳"
KEEP_TRIES = 20
KEEP_DELAY = 0.25


def run(cmd: list[str], want_json: bool = True):
    """Run a Herdr command; JSON in, SessionError with its stderr on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SessionError(f"{' '.join(cmd[:3])} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    if not want_json:
        return proc.stdout
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def state_from_title(title: str | None, status: str | None) -> str:
    """working / idle / <status>, from the agent's own status or its title glyph."""
    if status:
        return status
    glyph = (title or " ")[0]
    if glyph == IDLE:
        return "idle"
    if glyph in SPINNERS:
        return "working"
    return "unknown"


class HerdrBackend(SessionBackend):
    """Helpers as hc children of this terminal, shown in panes by herdr-app."""

    def __init__(self, runner=run, git=core.run_git):
        self.run = runner
        self.git = git

    def available(self) -> bool:
        return bool(os.environ.get("HC_TERMINAL_ID")) and shutil.which("hc") is not None

    def self_address(self) -> str:
        address = os.environ.get("HC_TERMINAL_ID")
        if not address:
            raise SessionError("not inside Herdr: $HC_TERMINAL_ID is unset")
        return address

    def names_in_use(self) -> set[str]:
        listing = self.run(["hc", "ls"])
        return {t["name"] for t in listing.get("terminals", []) if t.get("name")}

    def start(self, name, cwd, agent, message, labels, visible=True, worktree=None):
        argv = list(agent["argv"])
        tree = None
        if worktree:
            tree = core.worktree_path(cwd, name, self.git)
            branch = ["-b", worktree["branch"]] if worktree.get("branch") else ["--detach"]
            self.git(["-C", cwd, "worktree", "add", *branch, tree, worktree["ref"]])
            cwd, labels = tree, {**labels, "pair.worktree": tree}
        if argv and argv[0] == "codex" and "--no-daemon" not in argv:
            argv.insert(1, "--no-daemon")  # without it codex runs its commands outside hc
        cmd = ["hc", "run", "--bg", "--name", name, "--cwd", cwd]
        for key, value in labels.items():
            cmd += ["--label", f"{key}={value}"]
        out = self.run(cmd + argv + [message])
        address = out.get("address")
        if not address:
            raise SessionError(f"hc run returned no address for {name}: {out}")
        first = out.get("first_message")
        delivered = first.get("sent") if isinstance(first, dict) else None
        pane = None
        if visible:
            self.run(["herdr-app", "do", "pane.focus", "--terminal", self.self_address()])
            pane = self.keep(address).get("pane")
        return {"name": name, "address": address, "delivered": delivered, "pane": pane, "worktree": tree}

    def keep(self, address):
        """Show the helper in a pane right of the caller, once herdr-app can see it."""
        for attempt in range(KEEP_TRIES):
            try:
                return self.run(["herdr-app", "do", "terminal.keep", "--terminal", address, "--place", "right"])  # a name is refused
            except SessionError as err:
                if "no running terminal" not in str(err) or attempt == KEEP_TRIES - 1:
                    raise
                time.sleep(KEEP_DELAY)
        return {}

    def delegate(self, helper, message):
        out = self.run(["hc", "send", helper, message])
        return {"helper": helper, "sent": True, "started": out.get("started")}

    def collect(self, timeout):
        return self.run(["hc", "wait", "--children", "any", "--timeout", str(timeout), "--json"])

    def status(self, feature):
        listing = self.run(["hc", "ls", "--label", f"pair.feature={feature}"])
        helpers = []
        for t in listing.get("terminals", []):
            detail = self.run(["hc", "get", t["address"]])
            labels = detail.get("labels") or {}
            helpers.append({
                "name": t.get("name"),
                "address": t["address"],
                "agent": labels.get("pair.agent", t.get("agent")),
                "role": labels.get("pair.role"),
                "state": state_from_title(detail.get("title"), detail.get("status")),
            })
        return helpers

    def read(self, helper, lines):
        return self.run(["hc", "read", helper, "--lines", str(lines)], want_json=False)

    def stop(self, helper):
        tree = (self.run(["hc", "get", helper]).get("labels") or {}).get("pair.worktree")
        self.run(["hc", "kill", helper])
        try:
            self.run(["hc", "rm", helper])
        except SessionError:
            pass  # already removed
        if tree:
            self.git(["worktree", "remove", "--force", tree])  # it was ours: sm created it
        return {"helper": helper, "stopped": True, "removed_worktree": tree}

    def report_command(self, caller):
        return f"hc send {caller}"
