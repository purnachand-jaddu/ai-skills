import re
import tomllib
from pathlib import Path

from .interface import SessionError

AGENTS_FILE = Path(__file__).with_name("agents.toml")
NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


def agent_spec(agent: str) -> dict:
    """An agent type's launch details from agents.toml; each backend reads its own fields."""
    agents = tomllib.loads(AGENTS_FILE.read_text())
    if agent not in agents:
        raise SessionError(f"unknown agent {agent!r}; known: {', '.join(sorted(agents))} (add a row to agents.toml)")
    return dict(agents[agent], name=agent)


def repo_root(cwd: str, git=None) -> Path:
    """The repository's root folder: the bare clone itself, or a normal clone's top level."""
    git = git or run_git
    common = Path(git(["-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"]).strip())
    return common.parent if common.name == ".git" else common


def worktree_path(cwd: str, name: str, git=None) -> str:
    """Where a helper's worktree goes: beside the repo, named <repo>-<helper>."""
    repo = repo_root(cwd, git)
    return str(repo.parent / f"{repo.name}-{name}")


def inner_worktree_path(cwd: str, name: str, git=None) -> str:
    """A helper's worktree inside the repo folder, <repo>/.worktrees/<helper>, ignored via info/exclude."""
    git = git or run_git
    repo = repo_root(cwd, git)
    common = Path(git(["-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"]).strip())
    exclude = common / "info" / "exclude"
    if "/.worktrees/" not in (exclude.read_text() if exclude.exists() else ""):
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as f:
            f.write("\n/.worktrees/\n")  # local only, never committed
    return str(repo / ".worktrees" / name)


def run_git(args: list[str]) -> str:
    """Run git; SessionError with its stderr on failure."""
    import subprocess
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SessionError(f"git {' '.join(args[:3])} failed: {proc.stderr.strip()}")
    return proc.stdout


def helper_name(feature: str, role: str, taken: set[str]) -> str:
    """The first free name of <feature>-<role>, <feature>-<role>-2, …"""
    base = f"{feature}-{role}"
    for n in range(1, 100):
        name = base if n == 1 else f"{base}-{n}"
        if not NAME_RE.match(name):
            raise SessionError(f"helper name {name!r} must be 1-32 chars of a-z 0-9 - _; shorten the feature or role")
        if name not in taken:
            return name
    raise SessionError(f"no free name for {base!r}; stop old helpers first")


def envelope(feature: str, role: str, task_id: str, task: str, scope: str,
             rules: str, report_cmd: str) -> str:
    """The task message every helper gets, so results come back in one shape."""
    result = f"~/.agent-sessions/{feature}/{task_id}.md"
    return "\n".join([
        f"Role: {role}. {rules}".rstrip(),
        f"Task {task_id}: {task}",
        f"Scope: {scope}. Do not start other agents.",
        f"Write your full result to {result}:",
        "  first line a one-sentence verdict, then at most 10 bullets, then details.",
        f'Then run: {report_cmd} "{task_id} done: <verdict>. {result}"',
        "If stuck, send the question the same way instead.",
        "If that command reports the message as not started, it was still delivered; do not resend.",
    ])
