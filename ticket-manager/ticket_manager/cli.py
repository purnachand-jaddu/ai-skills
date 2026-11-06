import argparse
import json
import sys
from pathlib import Path

from . import lifecycle
from .interface import TicketBackend, TicketError


def parse_args(argv):
    p = argparse.ArgumentParser(prog="tm", description="Tickets linked to merge requests.")
    sub = p.add_subparsers(dest="op", required=True)
    g = sub.add_parser("get")
    g.add_argument("key")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=3)
    sub.add_parser("projects")
    c = sub.add_parser("columns")
    c.add_argument("project_id")
    cr = sub.add_parser("create")
    cr.add_argument("--project", required=True, help="project id")
    cr.add_argument("--title", required=True)
    cr.add_argument("--description-file", required=True)
    st = sub.add_parser("start")
    st.add_argument("key")
    st.add_argument("--branch", required=True)
    sy = sub.add_parser("sync")
    sy.add_argument("key")
    sy.add_argument("--relation", choices=["fixes", "refs"], required=True)
    sy.add_argument("--mr-state", choices=["open", "merged", "closed"], required=True)
    sy.add_argument("--draft", action="store_true")
    sy.add_argument("--valid-issues", action="store_true")
    sy.add_argument("--merged-into")
    sy.add_argument("--default-branch", default="main")
    sy.add_argument("--mr-ref", required=True, help="e.g. !881")
    sy.add_argument("--mr-url", required=True)
    sy.add_argument("--sha")
    sy.add_argument("--reasons-file", help="one draft reason per line")
    sy.add_argument("--state-file", help="pr-monitor's state file; remembers what was commented")
    ls = sub.add_parser("list")
    ls.add_argument("project_id")
    ls.add_argument("--status", help="one column slug")
    h = sub.add_parser("history")
    h.add_argument("key")
    rl = sub.add_parser("relations")
    rl.add_argument("key")
    sub.add_parser("reset-key")
    return p.parse_args(argv)


def load_state(path):
    if path and Path(path).exists():
        return json.loads(Path(path).read_text())
    return {}


def save_ticket_state(path, key, entry):
    if not path:
        return
    state = load_state(path)
    state.setdefault("tickets", {})[key] = entry
    Path(path).write_text(json.dumps(state, indent=2))


def start(backend, args):
    """Work begins: move to in-progress (guards apply) and say so once."""
    ticket = backend.get(args.key)
    move, why = lifecycle.plan_move(ticket["status"], backend.columns(ticket["project_id"]), "in-progress")
    if move:
        backend.move(ticket["id"], move)
        backend.comment(ticket["id"], f"Work started on branch `{args.branch}`")
    return {"ticket": ticket["key"], "url": ticket["url"], "from": ticket["status"], "to": move,
            "commented": bool(move), "why": why}


def sync(backend, args):
    """Bring the ticket in step with the MR: move first, then comment once per MR state."""
    ticket = backend.get(args.key)
    target = lifecycle.target_for(args.mr_state, args.draft, args.valid_issues, args.merged_into,
                                  args.default_branch, args.relation)
    move, why = lifecycle.plan_move(ticket["status"], backend.columns(ticket["project_id"]), target)
    if move:
        backend.move(ticket["id"], move)
    state_key = lifecycle.mr_state_key(args.mr_state, args.draft, args.merged_into)
    previous = load_state(args.state_file).get("tickets", {}).get(ticket["key"], {})
    commented = False
    if previous.get("last_mr_state") != state_key:
        reasons = Path(args.reasons_file).read_text().splitlines() if args.reasons_file else []
        backend.comment(ticket["id"], lifecycle.comment_for(
            args.mr_state, args.draft, args.merged_into, args.default_branch,
            args.mr_ref, args.mr_url, args.sha, [r for r in reasons if r.strip()]))
        commented = True
    save_ticket_state(args.state_file, ticket["key"], {
        "id": ticket["id"], "tracker": backend.name, "relation": args.relation,
        "last_status": move or ticket["status"], "last_mr_state": state_key})
    return {"ticket": ticket["key"], "url": ticket["url"], "from": ticket["status"], "to": move,
            "commented": commented, "why": why}


def dispatch(args, backend: TicketBackend):
    if args.op == "get":
        return backend.get(args.key)
    if args.op == "search":
        return backend.search(args.query, args.limit)
    if args.op == "projects":
        return backend.projects()
    if args.op == "columns":
        return backend.columns(args.project_id)
    if args.op == "create":
        return backend.create(args.project, args.title, Path(args.description_file).read_text())
    if args.op == "list":
        return backend.list(args.project_id, args.status)
    if args.op == "history":
        return backend.history(backend.get(args.key)["id"])
    if args.op == "relations":
        return backend.relations(backend.get(args.key)["id"])
    if args.op == "start":
        return start(backend, args)
    if args.op == "sync":
        return sync(backend, args)
    raise TicketError(f"unknown operation {args.op}")


def main(argv=None, backend: TicketBackend | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.op == "reset-key":
            from .backends.kaneo import reset_key
            reset_key()
            print(json.dumps({"reset": True}))
            return 0
        if backend is None:
            from .backends import load_backend
            backend = load_backend()
        out = dispatch(args, backend)
    except TicketError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0
