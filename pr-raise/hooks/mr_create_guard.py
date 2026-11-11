#!/usr/bin/env python3
"""PreToolUse hook: blocks `glab mr create` / `gh pr create` not run by pr-raise (PR_RAISE=1)."""
import json
import re
import sys

CREATE = re.compile(
    r"(?:^|[;&|(\n]|\$\(|\b(?:bash|sh|zsh)\s+(?:-\S+\s+)*-\w*c\s+[\"']?)\s*"
    r"((?:(?:[A-Za-z_]\w*=\S*|sudo|env|command|exec|nohup|time|timeout(?:\s+\d\S*)?|-\S+(?:\s+[^-\s]\S*)?)\s+)*)"
    r"(?:glab\s+mr\s+create|gh\s+pr\s+create)\b"
)
HEREDOC = re.compile(r"^(?P<open>.*?)<<-?\s*['\"]?(?P<tag>\w+)['\"]?(?P<rest>[^\n]*)\n(?P<body>.*?)^\s*(?P=tag)\s*$",
                     re.MULTILINE | re.DOTALL)
SHELL = re.compile(r"(?:^|[;&|(\s])(?:bash|sh|zsh)\b")
MESSAGE = (
    "Blocked: open MRs/PRs with the pr-raise skill, not by hand. It runs the checks, "
    "the review and starts pr-monitor. Several MRs: run pr-raise once per MR."
)


def without_data_heredocs(command: str) -> str:
    """Drops heredoc bodies that are data (a file, python), keeping ones fed to a shell."""
    def keep(m):
        line = m.group("open") + " " + m.group("rest")
        return m.group(0) if SHELL.search(line) else line + "\n"
    return HEREDOC.sub(keep, command)


def blocked(command: str) -> bool:
    """True when the command creates an MR/PR without the PR_RAISE=1 marker."""
    return any("PR_RAISE=1" not in m.group(1).split()
               for m in CREATE.finditer(without_data_heredocs(command)))


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
