# Agent registry

How session-manager starts each agent type. The launch details live in
`session_manager/agents.toml`, one field per backend: `argv` (herdr) and
`t3_provider` + `t3_model` (t3). The backend passes the first message as the
agent's opening prompt and may add flags its harness needs.

| Agent | Launch argv | Notes |
|---|---|---|
| `claude` | `claude --dangerously-skip-permissions` | The user's own argv for main sessions. `--model <id>` to pin a model |
| `codex` | `codex --dangerously-bypass-approvals-and-sandbox` | No sandbox: a Codex sandbox blocks the helper's report command and its result file. Same trust as the main Claude. On first start in a repo it may stop at "Hooks need review": a trust decision, ask the user ("Continue without trusting" is the safe answer). `-m <model>` to pin a model |

Checked against `claude --help` and `codex --help` (codex-cli 0.163.0) on
2026-11-03. Recheck the flags when a CLI updates.

## Read-only roles

Reviewer and researcher are read-only by **instruction**, not by sandbox: both
must still write their result file under `~/.agent-sessions/` and run the
report command, which any Codex sandbox and Claude's `plan` mode refuse. So:

- They run in a worktree, never in a bare checkout (`git status` fails there,
  and the check below has nothing to compare).
- Before the task: `git -C <worktree> status --porcelain > ~/.agent-sessions/<feature>/<task-id>.before`.
- After the report: compare again. Any change by a read-only role is reported
  to the user, never kept silently.

## Adding an agent

One row: its interactive launch argv (never a one-shot print mode like
`claude -p` or `codex exec`; helpers must stay steerable) and how it takes a
first message. Then `start` it once with the task "say hi and report hi" and
check the report arrives.
