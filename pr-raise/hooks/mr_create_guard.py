#!/usr/bin/env python3
"""PreToolUse hook: blocks `glab mr create` / `gh pr create` not run by pr-raise (PR_RAISE=1)."""
import json
import re
import sys

CREATE = re.compile(
    r"(?:^|[;&|(\n]|\$\()\s*((?:[A-Za-z_]\w*=\S*\s+)*)(?:glab\s+mr\s+create|gh\s+pr\s+create)\b"
)
MESSAGE = (
    "Blocked: open MRs/PRs with the pr-raise skill, not by hand. It runs the checks, "
    "the review and starts pr-monitor. Several MRs: run pr-raise once per MR."
)


def blocked(command: str) -> bool:
    """True when the command creates an MR/PR without the PR_RAISE=1 marker."""
    return any("PR_RAISE=1" not in m.group(1).split() for m in CREATE.finditer(command))


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    if blocked(command):
        print(MESSAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
