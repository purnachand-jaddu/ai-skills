#!/usr/bin/env python3
"""Launch and supervise headless Claude Code workers, one per ticket.

  launch --ticket ID --tier T0|T1|T2|T3 [--reason TEXT] [--repo PATH] [--base BRANCH] [--dry-run]
  status [--all]          table of runs (active only unless --all)
  kill RUN_ID             stop a run's process group
  cleanup RUN_ID          remove a finished run's worktree (branch is kept)
  retry TICKET_ID         forget failed/blocked attempts so the dispatcher re-picks it
  ctl RUN_ID OP [TEXT]    talk to a live worker: ping | say | steer | interrupt | stop | takeover

Each launch: git worktree on a fresh branch from origin/<base> -> detached
supervisor process -> `claude -p` with the tier's model, output streamed to
runs/<id>/stream.jsonl. The supervisor records the outcome in meta.json,
emits events, and reports failures back on the ticket.
"""
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve()
AI_SKILLS = HERE.parents[2]
sys.path.insert(0, str(AI_SKILLS / "lib"))
import fleet  # noqa: E402
import supervisor  # noqa: E402

TIERS = {
    # tier: model, effort (None = don't pass), timeout minutes
    "T0": {"model": "haiku", "effort": None, "timeout": 20, "label": "trivial"},
    "T1": {"model": "sonnet", "effort": "medium", "timeout": 45, "label": "small"},
    "T2": {"model": "sonnet", "effort": "high", "timeout": 90, "label": "medium"},
    "T3": {"model": "opus", "effort": "high", "timeout": 180, "label": "large"},
}

WORKER_RULES = """You are an autonomous worker in an agent fleet. Nobody is watching this
session live, so do not ask questions — decide, or stop and report.
- Work only inside your current git worktree, on the branch already checked out.
- Report milestones with: python3 {fleet} emit run.progress --msg "<one line>"
- Commit in small, conventional commits. Run the project's tests/linters if they exist.
- When the work is done, use the ship-mr skill to push and open the merge request.
- If the ticket is ambiguous, impossible, or needs a human decision, use the
  ship-mr skill's "blocked" path instead of guessing."""


def get_tracker():
    try:
        return fleet.tracker()
    except fleet.TicketError as e:  # tracker is optional for manual launches (--title)
        fleet.emit("tickets.error", msg=str(e))
        return None


def tracker_try(fn):
    """Tracker side-effects (status, comments) must never break a run."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        fleet.emit("tickets.error", msg=str(e) if isinstance(e, fleet.TicketError) else repr(e))


def slugify(text, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-") or "task"


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check,
                          capture_output=True, text=True)


def build_prompt(meta, ticket):
    desc = (ticket.get("description") or "").strip() or "(no description)"
    link = f"\nTracker link: {ticket['url']}\n" if ticket.get("url") else ""
    return f"""# Ticket {meta['ticket_ref']}: {meta['title']}

{desc}
{link}
---
Run id: {meta['run_id']}
Tier: {meta['tier']} ({TIERS[meta['tier']]['label']}) — router's note: {meta.get('reason') or 'n/a'}
Repository: {meta['repo']}
Worktree (your cwd): {meta['worktree']}
Branch: {meta['branch']}  (target: {meta['base']})

Implement this ticket, then ship it with the ship-mr skill.
"""


def cmd_launch(a):
    cfg = fleet.load_config()
    if a.tier not in TIERS:
        sys.exit(f"unknown tier {a.tier}; use one of {', '.join(TIERS)}")
    tr = get_tracker()
    if a.title:  # manual launch: no tracker lookup
        ticket = {"title": a.title, "description": a.description or ""}
    elif tr:
        try:
            ticket = tr.get(a.ticket)
        except fleet.TicketError as e:
            sys.exit(f"cannot read ticket {a.ticket}: {e}")
        a.ticket = ticket["key"]
    else:
        sys.exit("no ticket tracker available; pass --title/--description for a manual launch")

    projects = fleet.load_projects()
    project_id = ticket.get("project_id")
    pcfg = projects.get(project_id or "", {})
    repo = Path(a.repo or pcfg.get("repo") or "").expanduser()
    base = a.base or pcfg.get("base") or "main"
    if not repo or not (repo / ".git").exists():
        sys.exit(f"no git repo for ticket {a.ticket} (project {project_id}); "
                 f"map it in {fleet.PROJECTS} or pass --repo")
    # Several VMs may share one tracker: the status read just now is the claim check.
    status = ticket.get("status")
    if tr and not a.title and not a.force and status and status != fleet.PICK_STATUS:
        sys.exit(f"ticket {a.ticket} is '{status}', not '{fleet.PICK_STATUS}' — "
                 f"probably claimed by another node; pass --force to launch anyway")

    with fleet.locked("launch"):
        active = fleet.list_runs(active_only=True)
        if any(r.get("ticket_id") == a.ticket for r in active):
            sys.exit(f"ticket {a.ticket} already has an active run")
        limit = int(cfg["FLEET_MAX_PARALLEL"])
        if len(active) >= limit and not a.force:
            sys.exit(f"fleet is full ({len(active)}/{limit} active); try again later")

        ref = ticket.get("key") or a.ticket[:8]
        run_id = f"{time.strftime('%m%d-%H%M')}-{slugify(ref, 12)}-{uuid.uuid4().hex[:4]}"
        branch = f"agent/{slugify(ref, 12)}-{slugify(ticket["title"], 32)}"
        worktree = fleet.WORKTREES / run_id
        tier = TIERS[a.tier]
        meta = {
            "run_id": run_id, "state": "queued", "created_at": fleet.now(),
            "ticket_id": a.ticket, "ticket_ref": ref, "title": ticket["title"],
            "project_id": project_id, "ticket_url": ticket.get("url"), "tier": a.tier,
            "model": tier["model"], "effort": tier["effort"], "reason": a.reason,
            "repo": str(repo), "base": base, "branch": branch, "worktree": str(worktree),
        }
        if a.dry_run:
            print(json.dumps({"dry_run": True, **meta}, indent=2))
            return
        fleet.write_meta(run_id, meta)  # reserve the slot before releasing the lock

    node = cfg["FLEET_NODE"]
    if tr:  # claim first, before slow git work, so other nodes stop seeing it as to-do
        tracker_try(lambda: fleet.tm.move(tr, a.ticket, "in-progress"))

    try:
        git(repo, "fetch", "origin", base)
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0:
            branch = f"{branch}-{run_id[-4:]}"
            fleet.update_meta(run_id, branch=branch)
            meta["branch"] = branch
        git(repo, "worktree", "add", "-b", branch, str(worktree), f"origin/{base}")
    except subprocess.CalledProcessError as e:
        fleet.update_meta(run_id, state="failed", error=f"worktree: {e.stderr.strip()}")
        fleet.emit("run.failed", run_id, a.ticket, "could not create worktree", stderr=e.stderr[-500:])
        if tr:  # release the claim
            tracker_try(lambda: fleet.tm.move(tr, a.ticket, fleet.PICK_STATUS))
        sys.exit(f"git failed: {e.stderr}")

    (fleet.run_dir(run_id) / "prompt.md").write_text(build_prompt(meta, ticket))
    sup = subprocess.Popen(
        [sys.executable, str(HERE), "_supervise", run_id],
        start_new_session=True, stdin=subprocess.DEVNULL,
        stdout=open(fleet.run_dir(run_id) / "supervisor.log", "a"), stderr=subprocess.STDOUT)
    fleet.update_meta(run_id, supervisor_pid=sup.pid)
    fleet.emit("run.launched", run_id, a.ticket, ticket["title"],
               tier=a.tier, model=tier["model"], branch=branch, reason=a.reason)

    if tr:
        tracker_try(lambda: fleet.tm.comment(tr, a.ticket,
            f"🤖 Picked up by agent run `{run_id}` on `{node}` — tier {a.tier} ({tier['label']}), "
            f"model `{tier['model']}`, branch `{branch}`.\n\nRouter: {a.reason or 'n/a'}"))
    print(json.dumps({"launched": run_id, "branch": branch, "model": tier["model"]}))


def worker_cmd(meta, cfg):
    cmd = ["claude", "-p", "--model", meta["model"], "--verbose",
           "--input-format", "stream-json", "--output-format", "stream-json",
           "--append-system-prompt", WORKER_RULES.format(fleet=AI_SKILLS / "lib" / "fleet.py")]
    if meta.get("effort"):
        cmd += ["--effort", meta["effort"]]
    if cfg["FLEET_WORKER_PERMS"] == "bypass":
        cmd += ["--dangerously-skip-permissions"]
    else:
        cmd += ["--permission-mode", "acceptEdits",
                "--allowedTools", *shlex.split(cfg["FLEET_ALLOWED_TOOLS"]),
                f"Bash(python3 {AI_SKILLS}:*)", "Bash(python3 ~/codebase/ai-skills:*)"]
    return cmd


def cmd_supervise(a):
    run_id = a.run_id
    cfg = fleet.load_config()
    meta = fleet.read_meta(run_id)
    tr = get_tracker()

    def comment(text):
        if tr:
            tracker_try(lambda: fleet.tm.comment(tr, meta["ticket_id"], text))

    sup = supervisor.Supervisor(run_id, worker_cmd(meta, cfg), comment)
    out = sup.run((fleet.run_dir(run_id) / "prompt.md").read_text(),
                  TIERS[meta["tier"]]["timeout"] * 60)
    code, res = out["exit_code"], out["result"]

    meta = fleet.read_meta(run_id)  # ship-mr may have written mr_url / blocked meanwhile
    if meta.get("state") == "killed":
        state = "killed"
    elif sup.finish == "takeover" and out.get("takeover"):
        state = "taken-over"
    elif meta.get("mr_url"):
        state = "done"
    elif sup.finish in ("stop", "takeover"):
        state = "stopped"
    elif meta.get("blocked"):
        state = "blocked"
    elif out["timed_out"]:
        state = "timeout"
    elif code != 0 or res.get("is_error"):
        state = "failed"
    else:
        state = "no-mr"  # finished cleanly but never opened an MR
    fleet.update_meta(run_id, state=state, exit_code=code, finished_at=fleet.now(),
                      cost_usd=res.get("total_cost_usd"), turns=res.get("num_turns"),
                      summary=(res.get("result") or "")[-2000:])
    fleet.emit(f"run.{state}", run_id, meta["ticket_id"], meta.get("mr_url") or meta["title"],
               cost_usd=res.get("total_cost_usd"), exit_code=code)

    if state in ("failed", "timeout", "no-mr"):
        tail = (res.get("result") or "").strip()[-800:] or "(no summary)"
        comment(f"⚠️ Agent run `{run_id}` ended as **{state}** (exit {code}). "
                f"Branch `{meta['branch']}` kept for inspection.\n\n> {tail}")
        if tr:
            tracker_try(lambda: fleet.tm.move(tr, meta["ticket_id"], fleet.PICK_STATUS))


def cmd_ctl(a):
    reply = supervisor.ctl(a.run_id, a.op, " ".join(a.text) if a.text else None,
                           by=a.by or os.environ.get("USER", "cli"))
    print(json.dumps(reply, indent=2))
    sys.exit(0 if reply.get("ok") else 1)


def cmd_status(a):
    runs = fleet.list_runs(active_only=not a.all)
    if a.json:
        print(json.dumps(runs, indent=2))
        return
    if not runs:
        print("no runs" if a.all else "no active runs")
        return
    for r in runs:
        cost = f"${r['cost_usd']:.2f}" if r.get("cost_usd") else ""
        print(f"{r['run_id']:<28} {r.get('state',''):<9} {r.get('tier','')} {r.get('model',''):<7} "
              f"{cost:>7}  {r.get('title','')[:50]}  {r.get('mr_url','')}")


def cmd_kill(a):
    meta = fleet.read_meta(a.run_id) or sys.exit("no such run")
    fleet.update_meta(a.run_id, state="killed")
    for key in ("worker_pid", "supervisor_pid"):
        pid = meta.get(key)
        if fleet.pid_alive(pid):
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
    if supervisor.tmux_alive(a.run_id):
        subprocess.run(["tmux", "kill-session", "-t", supervisor.tmux_session(a.run_id)])
    supervisor.kill_run_processes(a.run_id, exclude_tmux=False)
    fleet.emit("run.killed", a.run_id, meta.get("ticket_id"))
    print(f"killed {a.run_id}")


def cmd_retry(a):
    n = 0
    for r in fleet.list_runs():
        if r.get("ticket_id") == a.ticket and r.get("state") not in fleet.ACTIVE_STATES | {"done"}:
            fleet.update_meta(r["run_id"], retry_cleared=True)
            n += 1
    fleet.emit("ticket.retry", ticket=a.ticket, msg=f"cleared {n} previous attempt(s)")
    print(f"cleared {n} previous attempt(s); ticket {a.ticket} is pickable again")


def cmd_cleanup(a):
    meta = fleet.read_meta(a.run_id) or sys.exit("no such run")
    if meta.get("state") in fleet.ACTIVE_STATES:
        sys.exit("run is still active; kill it first")
    r = git(meta["repo"], "worktree", "remove", "--force", meta["worktree"], check=False)
    print(r.stdout or r.stderr or f"removed {meta['worktree']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("launch")
    p.add_argument("--ticket", required=True)
    p.add_argument("--tier", required=True, type=str.upper)
    p.add_argument("--reason", default="")
    p.add_argument("--repo"); p.add_argument("--base")
    p.add_argument("--title", help="skip the tracker lookup (manual/offline launch)")
    p.add_argument("--description")
    p.add_argument("--force", action="store_true", help="ignore FLEET_MAX_PARALLEL")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("_supervise"); p.add_argument("run_id")
    p = sub.add_parser("status"); p.add_argument("--all", action="store_true")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("kill"); p.add_argument("run_id")
    p = sub.add_parser("cleanup"); p.add_argument("run_id")
    p = sub.add_parser("retry"); p.add_argument("ticket")
    p = sub.add_parser("ctl", help="control a live worker")
    p.add_argument("run_id")
    p.add_argument("op", choices=["ping", "say", "steer", "interrupt", "stop", "takeover"])
    p.add_argument("text", nargs="*")
    p.add_argument("--by")
    a = ap.parse_args()
    {"launch": cmd_launch, "_supervise": cmd_supervise, "status": cmd_status,
     "kill": cmd_kill, "cleanup": cmd_cleanup, "retry": cmd_retry,
     "ctl": cmd_ctl}[a.cmd](a)


if __name__ == "__main__":
    main()
