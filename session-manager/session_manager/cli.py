import argparse
import json
import sys

from . import core
from .interface import SessionBackend, SessionError


def parse_args(argv):
    p = argparse.ArgumentParser(prog="sm", description="Helper sessions for the current agent session.")
    sub = p.add_subparsers(dest="op", required=True)
    sub.add_parser("available")
    sub.add_parser("self")
    s = sub.add_parser("start")
    s.add_argument("--feature", required=True)
    s.add_argument("--role", required=True)
    s.add_argument("--agent", default="claude")
    s.add_argument("--cwd", required=True)
    msg = s.add_mutually_exclusive_group(required=True)
    msg.add_argument("--message")
    msg.add_argument("--message-file")
    s.add_argument("--hidden", action="store_true", help="no pane beside the caller")
    s.add_argument("--worktree-from", metavar="REF", help="run in a new git worktree of --cwd's repo at REF")
    s.add_argument("--branch", help="branch for that worktree (default: detached)")
    d = sub.add_parser("delegate")
    d.add_argument("helper")
    dm = d.add_mutually_exclusive_group(required=True)
    dm.add_argument("--message")
    dm.add_argument("--message-file")
    c = sub.add_parser("collect")
    c.add_argument("--timeout", type=int, default=180)
    st = sub.add_parser("status")
    st.add_argument("--feature", required=True)
    r = sub.add_parser("read")
    r.add_argument("helper")
    r.add_argument("--lines", type=int, default=40)
    sp = sub.add_parser("stop")
    sp.add_argument("helper")
    fg = sub.add_parser("forget", help="drop a helper the backend can't stop from its registry")
    fg.add_argument("helper")
    rc = sub.add_parser("report-cmd")
    rc.add_argument("--caller")
    e = sub.add_parser("envelope")
    for flag in ("--feature", "--role", "--task-id", "--task", "--scope"):
        e.add_argument(flag, required=True)
    e.add_argument("--rules", default="")
    e.add_argument("--caller")
    return p.parse_args(argv)


def message_of(args) -> str:
    if args.message is not None:
        return args.message
    with open(args.message_file) as f:
        return f.read()


def dispatch(args, backend: SessionBackend):
    """Run one operation; returns what to print (dict/list as JSON, str as text)."""
    if args.op == "available":
        return {"available": backend.available()}
    if args.op == "self":
        return {"address": backend.self_address()}
    if args.op == "start":
        name = core.helper_name(args.feature, args.role, backend.names_in_use())
        labels = {"pair.feature": args.feature, "pair.role": args.role, "pair.agent": args.agent}
        worktree = {"ref": args.worktree_from, "branch": args.branch} if args.worktree_from else None
        return backend.start(name, args.cwd, core.agent_spec(args.agent), message_of(args), labels,
                             visible=not args.hidden, worktree=worktree)
    if args.op == "delegate":
        return backend.delegate(args.helper, message_of(args))
    if args.op == "collect":
        return backend.collect(args.timeout)
    if args.op == "status":
        return backend.status(args.feature)
    if args.op == "read":
        return backend.read(args.helper, args.lines)
    if args.op == "stop":
        return backend.stop(args.helper)
    if args.op == "forget":
        if not hasattr(backend, "forget"):
            raise SessionError("this backend keeps no registry; use stop")
        return backend.forget(args.helper)
    if args.op == "report-cmd":
        return {"command": backend.report_command(args.caller or backend.self_address())}
    if args.op == "envelope":
        report = backend.report_command(args.caller or backend.self_address())
        return core.envelope(args.feature, args.role, args.task_id, args.task, args.scope, args.rules, report)
    raise SessionError(f"unknown operation {args.op}")


def main(argv=None, backend: SessionBackend | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if backend is None:
            from .backends import load_backend
            backend = load_backend()
        out = dispatch(args, backend)
    except SessionError as err:
        print(json.dumps({"error": str(err)}), file=sys.stderr)
        return 1
    print(out if isinstance(out, str) else json.dumps(out, indent=2))
    return 0
