#!/usr/bin/env python3
"""Finish a fleet run: push the branch and open a GitLab MR, or report blocked.

  ship.py mr --title T --body-file F|- [--draft]   (- reads the body from stdin)
  ship.py blocked --reason TEXT

Run from inside the worker's worktree. Reads FLEET_RUN_ID from the env (set by
the launcher), so the MR link lands in the run's meta, the event stream, and
as a comment on the ticket, which ticket-manager moves to in-review (in-progress for a Draft).
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

AI_SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AI_SKILLS / "lib"))
import fleet  # noqa: E402


def sh(*cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"$ {' '.join(cmd)}\n{r.stdout}{r.stderr}")
    return r


def tracker_side_effects(meta, update):
    try:
        update(fleet.tracker())
    except Exception as e:  # noqa: BLE001 - never lose the MR over a tracker hiccup
        fleet.emit("tickets.error", meta["run_id"], meta["ticket_id"], str(e))
        print(f"warning: ticket update failed: {e}", file=sys.stderr)


def sync_ticket(backend, meta, url, iid, sha, draft):
    """ticket-manager's MR sync: moves the ticket, then comments once for this MR state."""
    args = ["sync", meta["ticket_id"], "--relation", "fixes", "--mr-state", "open",
            "--mr-ref", f"!{iid}", "--mr-url", url, "--sha", sha,
            "--state-file", str(fleet.run_dir(meta["run_id"]) / "ticket-state.json")]
    fleet.tm.sync(backend, fleet.tm.parse_args(args + (["--draft"] if draft else [])))


def load_run():
    run_id = os.environ.get("FLEET_RUN_ID")
    meta = fleet.read_meta(run_id) if run_id else None
    if not meta:
        sys.exit("FLEET_RUN_ID not set or unknown — are you running inside a fleet worker?")
    return meta


def cmd_mr(a):
    meta = load_run()
    branch = sh("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != meta["branch"]:
        sys.exit(f"on branch {branch}, expected {meta['branch']}")
    if sh("git", "status", "--porcelain").stdout.strip():
        sys.exit("worktree has uncommitted changes — commit (or discard) them first")
    ahead = sh("git", "rev-list", "--count", f"origin/{meta['base']}..HEAD").stdout.strip()
    if ahead == "0":
        sys.exit("no commits on this branch — nothing to ship")

    sh("git", "push", "-u", "origin", branch)
    body = sys.stdin.read() if a.body_file == "-" else Path(a.body_file).read_text()
    ticket = f"[{meta['ticket_ref']}]({meta['ticket_url']})" if meta.get("ticket_url") else meta["ticket_ref"]
    body += f"\n\n---\nTicket: {ticket} · fleet run `{meta['run_id']}` · " \
            f"tier {meta['tier']} / {meta['model']}\n"
    cmd = ["glab", "mr", "create", "--source-branch", branch, "--target-branch", meta["base"],
           "--title", a.title, "--description", body, "--remove-source-branch", "--yes"]
    if a.draft:
        cmd.append("--draft")
    out = sh(*cmd)
    m = re.search(r"https?://\S+/-/merge_requests/(\d+)", out.stdout + out.stderr)
    if not m:
        sys.exit(f"MR created? could not find its URL in glab output:\n{out.stdout}{out.stderr}")
    url = m.group(0)

    fleet.update_meta(meta["run_id"], mr_url=url, mr_title=a.title)
    fleet.emit("mr.opened", meta["run_id"], meta["ticket_id"], url, title=a.title, commits=int(ahead))
    sha = sh("git", "rev-parse", "HEAD").stdout.strip()
    tracker_side_effects(meta, lambda tr: sync_ticket(tr, meta, url, m.group(1), sha, a.draft))
    print(url)


def cmd_blocked(a):
    meta = load_run()
    fleet.update_meta(meta["run_id"], blocked=a.reason)
    fleet.emit("run.blocked", meta["run_id"], meta["ticket_id"], a.reason)
    text = f"🛑 Agent run `{meta['run_id']}` needs a human:\n\n{a.reason}"

    def update(tr):
        fleet.tm.comment(tr, meta["ticket_id"], text)
        fleet.tm.move(tr, meta["ticket_id"], fleet.PICK_STATUS)
    tracker_side_effects(meta, update)
    print("marked blocked")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("mr")
    p.add_argument("--title", required=True)
    p.add_argument("--body-file", required=True)
    p.add_argument("--draft", action="store_true")
    p = sub.add_parser("blocked")
    p.add_argument("--reason", required=True)
    a = ap.parse_args()
    {"mr": cmd_mr, "blocked": cmd_blocked}[a.cmd](a)


if __name__ == "__main__":
    main()
