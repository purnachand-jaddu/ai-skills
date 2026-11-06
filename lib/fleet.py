#!/usr/bin/env python3
"""Shared state for the agent fleet: config, event log, run registry.

Everything lives under $FLEET_HOME (default ~/.agent-fleet):
  config.env        KEY=VALUE settings (ticket backend, limits, worker perms)
  projects.json     tracker project id -> {"repo": "/path", "base": "main"}
  events.jsonl      append-only event stream (the dashboard tails this)
  runs/<run_id>/    meta.json, stream.jsonl (claude output), stderr.log
  worktrees/<run_id>  git worktree each worker edits in

CLI (used from skills via bash):
  fleet.py emit <kind> [--run ID] [--ticket ID] [--msg TEXT] [--data JSON]
  fleet.py runs [--active]
  fleet.py config
  fleet.py health                 tracker reachable and key valid
  fleet.py pickable               tickets the dispatcher may start now, best first
"""
import argparse
import fcntl
import json
import os
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ticket-manager"))
from ticket_manager import cli as tm  # noqa: E402
from ticket_manager.backends import load_backend  # noqa: E402
from ticket_manager.interface import TicketError  # noqa: E402

FLEET_HOME = Path(os.environ.get("FLEET_HOME", Path.home() / ".agent-fleet"))
EVENTS = FLEET_HOME / "events.jsonl"
RUNS = FLEET_HOME / "runs"
WORKTREES = FLEET_HOME / "worktrees"
CONFIG = FLEET_HOME / "config.env"
PROJECTS = FLEET_HOME / "projects.json"

ACTIVE_STATES = {"queued", "running"}
PICK_STATUS = "to-do"  # the column workers pick from, and where blocked or failed tickets go back to
PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}

DEFAULTS = {
    "FLEET_NODE": socket.gethostname(),  # this machine's name on tickets/events (multi-VM)
    "KANEO_API_KEY": "",  # the rest of the tracker's settings are ticket-manager's config.toml
    "FLEET_PICK_LABEL": "",  # optional: only pick tickets carrying this label
    "FLEET_MAX_PARALLEL": "3",
    "FLEET_MAX_ATTEMPTS": "1",  # unsuccessful runs before a ticket stops being auto-picked
    "FLEET_WORKER_PERMS": "allowlist",  # "allowlist" or "bypass"
    "FLEET_ALLOWED_TOOLS": (
        "Read Edit Write Glob Grep Skill "
        "Bash(git:*) Bash(glab:*) Bash(python3:*) Bash(node:*) Bash(npm:*) "
        "Bash(npx:*) Bash(pnpm:*) Bash(yarn:*) Bash(make:*) Bash(pytest:*) "
        "Bash(ls:*) Bash(cat:*) Bash(head:*) Bash(tail:*) Bash(grep:*) "
        "Bash(find:*) Bash(sed:*) Bash(wc:*) Bash(mkdir:*)"
    ),
    "DASHBOARD_PORT": "8787",
    "DASHBOARD_TOKEN": "",
    "DASHBOARD_CONTROL": "0",  # 1 = steering buttons + browser takeover terminal
}


def ensure_dirs():
    for d in (FLEET_HOME, RUNS, WORKTREES):
        d.mkdir(parents=True, exist_ok=True)


def load_config():
    cfg = dict(DEFAULTS)
    if CONFIG.exists():
        for line in CONFIG.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    # Environment variables override any key the defaults or config.env define
    # (so backend-specific settings work too, once named in config.env).
    for k in list(cfg):
        if k in os.environ:
            cfg[k] = os.environ[k]
    return cfg


def tracker():
    """The ticket-manager backend, using the API key from config.env."""
    key = load_config()["KANEO_API_KEY"]
    if key:
        os.environ["KANEO_API_KEY"] = key
    return load_backend()


def load_projects():
    if PROJECTS.exists():
        return json.loads(PROJECTS.read_text())
    return {}


def pickable(backend, cfg, runs, projects):
    """Tickets the dispatcher may start: in the pick column, in a mapped project, carrying the
    pick label if one is set, without an active run, and not out of attempts. Ordered by
    priority, then oldest first."""
    busy = {r.get("ticket_id") for r in runs if r.get("state") in ACTIVE_STATES}
    failed = {}
    for r in runs:
        if r.get("state") not in ACTIVE_STATES | {"done"} and not r.get("retry_cleared"):
            failed[r.get("ticket_id")] = failed.get(r.get("ticket_id"), 0) + 1
    max_attempts = int(cfg["FLEET_MAX_ATTEMPTS"])
    want_label = cfg["FLEET_PICK_LABEL"].lower()

    out = []
    for project_id, pcfg in projects.items():
        if project_id.startswith("<"):  # example placeholder entry
            continue
        for t in backend.list(project_id, PICK_STATUS):
            if t["status"] != PICK_STATUS or t["key"] in busy:
                continue
            if failed.get(t["key"], 0) >= max_attempts:
                continue  # needs a human; `fleet retry <ticket>` re-enables
            if want_label and want_label not in {l.lower() for l in backend.labels(t["id"])}:
                continue
            out.append({**t, "project_id": project_id, "repo": pcfg.get("repo")})
    out.sort(key=lambda t: (PRIORITY_ORDER.get((t.get("priority") or "").lower(), 9),
                            t.get("created_at") or ""))
    return out


@contextmanager
def locked(name="fleet"):
    ensure_dirs()
    with open(FLEET_HOME / f".{name}.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def emit(kind, run_id=None, ticket=None, msg=None, **data):
    ensure_dirs()
    ev = {"ts": now(), "kind": kind, "node": load_config()["FLEET_NODE"]}
    if run_id:
        ev["run"] = run_id
    if ticket:
        ev["ticket"] = ticket
    if msg:
        ev["msg"] = msg
    if data:
        ev["data"] = data
    line = json.dumps(ev, ensure_ascii=False) + "\n"
    with open(EVENTS, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(line)
        fcntl.flock(fh, fcntl.LOCK_UN)
    return ev


def run_dir(run_id):
    return RUNS / run_id


def read_meta(run_id):
    p = run_dir(run_id) / "meta.json"
    return json.loads(p.read_text()) if p.exists() else None


def write_meta(run_id, meta):
    d = run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, indent=2))
    tmp.replace(d / "meta.json")


def update_meta(run_id, **fields):
    with locked(f"run-{run_id}"):
        meta = read_meta(run_id) or {"run_id": run_id}
        meta.update(fields)
        meta["updated_at"] = now()
        write_meta(run_id, meta)
        return meta


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def list_runs(active_only=False):
    ensure_dirs()
    out = []
    for d in sorted(RUNS.iterdir(), reverse=True):
        meta = read_meta(d.name)
        if not meta:
            continue
        # A supervisor that died without recording an outcome is "lost".
        if meta.get("state") in ACTIVE_STATES and meta.get("supervisor_pid") \
                and not pid_alive(meta["supervisor_pid"]):
            meta = update_meta(d.name, state="lost")
            emit("run.lost", run_id=d.name, ticket=meta.get("ticket_id"))
        if active_only and meta.get("state") not in ACTIVE_STATES:
            continue
        out.append(meta)
    return out


def _main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit")
    e.add_argument("kind")
    e.add_argument("--run", default=os.environ.get("FLEET_RUN_ID"))
    e.add_argument("--ticket", default=os.environ.get("FLEET_TICKET_ID"))
    e.add_argument("--msg")
    e.add_argument("--data", help="JSON object of extra fields")
    r = sub.add_parser("runs")
    r.add_argument("--active", action="store_true")
    sub.add_parser("config")
    sub.add_parser("health")
    sub.add_parser("pickable")
    a = ap.parse_args()
    if a.cmd == "emit":
        extra = json.loads(a.data) if a.data else {}
        print(json.dumps(emit(a.kind, a.run, a.ticket, a.msg, **extra)))
    elif a.cmd == "runs":
        print(json.dumps(list_runs(a.active), indent=2))
    elif a.cmd in ("health", "pickable"):
        try:
            backend = tracker()
            out = tm.health(backend) if a.cmd == "health" else \
                pickable(backend, load_config(), list_runs(), load_projects())
        except TicketError as e:
            sys.exit(f"error: {e}")
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif a.cmd == "config":
        cfg = load_config()
        for k in list(cfg):  # mask secrets of any backend
            if any(s in k for s in ("API_KEY", "TOKEN", "SECRET", "PASSWORD")) and cfg[k] \
                    and k != "DASHBOARD_TOKEN":
                cfg[k] = cfg[k][:6] + "…"
        if cfg.get("DASHBOARD_TOKEN"):
            cfg["DASHBOARD_TOKEN"] = "set"
        print(json.dumps({"home": str(FLEET_HOME), **cfg,
                          "projects": load_projects()}, indent=2))


if __name__ == "__main__":
    sys.exit(_main())
