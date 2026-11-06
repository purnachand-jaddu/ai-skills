import json
import os
import subprocess
import time
from pathlib import Path

from .. import core
from ..interface import SessionBackend, SessionError

REGISTRY = Path.home() / ".agent-sessions" / ".t3-helpers.json"
WORKING = {"preparing", "queued", "starting", "running"}
NEWS = {"blocked", "failed", "interrupted", "cancelled"}
POLL_SECONDS = 5


def cli_path() -> str:
    return os.environ.get("T3CODE_CLI_PATH") or str(Path.home() / ".t3" / "bin" / "t3")


def run(args: list[str], want_json: bool = True):
    """Run a t3 command; JSON in, SessionError with its output on failure."""
    proc = subprocess.run([cli_path(), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SessionError(f"t3 {' '.join(args[:2])} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    if not want_json:
        return proc.stdout
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def state_of(thread: dict) -> str:
    """working / blocked / idle / <terminal status>, from a T3 thread record."""
    if thread.get("pendingRequestCount"):
        return "blocked"
    status = thread.get("status", "unknown")
    if status in WORKING:
        return "working"
    if status in ("idle", "completed"):
        return "idle"
    return status


class T3Backend(SessionBackend):
    """Helpers as T3 Code threads, driven through the t3 CLI; a registry maps helper names to threads."""

    def __init__(self, runner=run, registry: Path = REGISTRY, sleep=time.sleep, git=core.run_git):
        self.run = runner
        self.git = git
        self.registry = registry
        self.sleep = sleep

    def load(self) -> dict:
        return json.loads(self.registry.read_text()) if self.registry.exists() else {}

    def save(self, helpers: dict) -> None:
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(json.dumps(helpers, indent=2))

    def mine(self) -> dict:
        """Helpers this session started."""
        me = self.self_address()
        return {name: h for name, h in self.load().items() if h.get("caller") == me}

    def thread_id(self, helper: str) -> str:
        helpers = self.load()
        if helper not in helpers:
            raise SessionError(f"no helper named {helper!r} in {self.registry}; see `sm status`")
        return helpers[helper]["thread"]

    def show(self, thread: str, messages: int = 1) -> dict:
        return self.run(["thread", "show", "--json", "--messages", str(messages), thread])

    def available(self) -> bool:
        return bool(os.environ.get("T3CODE_THREAD_ID")) and Path(cli_path()).exists()

    def self_address(self) -> str:
        address = os.environ.get("T3CODE_THREAD_ID")
        if not address:
            raise SessionError("not inside T3 Code: $T3CODE_THREAD_ID is unset")
        return address

    def names_in_use(self) -> set[str]:
        return set(self.load())

    def start(self, name, cwd, agent, message, labels, visible=True, worktree=None):
        if "t3_provider" not in agent:
            raise SessionError(f"agent {agent.get('name')!r} has no t3_provider in agents.toml")
        tree = None
        if worktree:
            # T3's own --worktree can't drive a bare clone, so sm makes it inside the project folder
            tree = core.inner_worktree_path(cwd, name, self.git)
            branch = ["-b", worktree["branch"]] if worktree.get("branch") else ["--detach"]
            self.git(["-C", cwd, "worktree", "add", *branch, tree, worktree["ref"]])
            cwd = tree
        out = self.run(["thread", "start", "--json", "--title", name, "--provider", agent["t3_provider"],
                        "--model", agent["t3_model"], cwd, message])
        thread = out.get("threadId") or out.get("thread", {}).get("threadId") or out.get("id")
        if not thread:
            raise SessionError(f"t3 thread start returned no thread id for {name}: {out}")
        helpers = self.load()
        helpers[name] = {"thread": thread, "caller": self.self_address(), "cwd": cwd, "worktree": tree, **labels}
        self.save(helpers)
        return {"name": name, "address": thread, "delivered": True, "pane": None, "worktree": tree,
                "link": out.get("link") or out.get("thread", {}).get("link")}

    def delegate(self, helper, message):
        self.run(["thread", "send", "--json", self.thread_id(helper), message])
        return {"helper": helper, "sent": True, "started": None}

    def collect(self, timeout):
        """Poll this session's helpers until one stops working or blocks (the CLI has no wait)."""
        before = {n: state_of(self.show(h["thread"])["thread"]) for n, h in self.mine().items()}
        for name, state in before.items():
            if state in NEWS:
                return {"reason": state, "helper": name, "address": self.load()[name]["thread"]}  # news before we waited
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.sleep(POLL_SECONDS)
            for name, helper in self.mine().items():
                now = state_of(self.show(helper["thread"])["thread"])
                if now != before.get(name) and now != "working":
                    return {"reason": now, "helper": name, "address": helper["thread"]}
        return {"reason": "timeout", "helpers": before}

    def status(self, feature):
        rows = []
        for name, helper in self.load().items():
            if helper.get("pair.feature") != feature:
                continue
            thread = self.show(helper["thread"])["thread"]
            rows.append({"name": name, "address": helper["thread"], "agent": helper.get("pair.agent"),
                         "role": helper.get("pair.role"), "state": state_of(thread)})
        return rows

    def read(self, helper, lines):
        return self.run(["thread", "show", "--messages", str(max(1, lines // 10)), self.thread_id(helper)],
                        want_json=False)

    def stop(self, helper):
        thread = self.thread_id(helper)
        raise SessionError(f"the t3 CLI cannot stop a thread; stop {thread} with T3 Code's thread interrupt "
                           f"(stop: true) or in the app, then run `sm forget {helper}`")

    def forget(self, helper):
        helpers = self.load()
        tree = helpers.pop(helper, {}).get("worktree")
        if tree:
            self.git(["worktree", "remove", "--force", tree])  # it was ours: sm created it
        self.save(helpers)
        return {"helper": helper, "forgotten": True, "removed_worktree": tree}

    def report_command(self, caller):
        return f"{cli_path()} thread send {caller}"
