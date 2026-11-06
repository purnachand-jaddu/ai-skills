---
name: agent-launcher
description: Launch, monitor, kill, retry, and clean up fleet worker agents — each ticket gets its own git worktree, branch, and headless Claude Code process at the model chosen by tier (T0 haiku → T3 opus). Use to start work on a ticket at a given tier, check what agents are running, or stop/clean up a run.
---

# Agent launcher

CLI: `python3 ~/codebase/ai-skills/agent-launcher/scripts/launch_agent.py <command>`
(also `fleet status|kill|retry|cleanup`).

| Command | Does |
|---|---|
| `launch --ticket ID --tier T0..T3 --reason "…"` | Start a worker. Add `--dry-run` to preview, `--repo/--base` to override the project mapping, `--title/--description` to launch without Kaneo. |
| `status [--all] [--json]` | Runs table: state, tier, model, cost, MR link. |
| `kill RUN_ID` | SIGTERM the worker's process group; state → `killed`. |
| `retry TICKET_ID` | Forget failed/blocked attempts so the dispatcher can pick the ticket again. |
| `cleanup RUN_ID` | Remove a finished run's worktree (the branch stays). |
| `ctl RUN_ID ping\|say\|steer\|interrupt\|stop\|takeover [TEXT]` | Talk to a live worker (also `fleet steer/say/stop/takeover`). |

## Steering and takeover
Workers run `claude -p --input-format stream-json`, and the supervisor listens on a
per-run Unix socket (`runs/<id>/control.sock`, owner-only):

- `fleet steer <run> "msg"`: interrupt the current turn (≈0.1s) and send the message; the
  session keeps its context. Logged and commented on the ticket.
- `fleet say <run> "msg"`: deliver at the end of the current turn, no interrupt.
- `fleet stop <run>`: interrupt, close input, kill the worker's process group, then reap any
  process still carrying its `FLEET_RUN_ID` (Claude Code runs tool commands in their own
  process groups, so a group kill alone can miss them). State → `stopped`.
- `fleet takeover <run>`: stop, then reopen the same session with `claude --resume` in tmux
  session `fleet-<run>`; `fleet attach <run>` to join. State → `taken-over` (frees the slot).
  First open of a worktree shows Claude Code's folder-trust prompt; that's yours to answer.

A worker that finishes a turn stays open for steering for 60s (`IDLE_GRACE` in
`supervisor.py`), unless it already shipped an MR or reported blocked.

## What a launch does
1. Checks the fleet isn't full (`FLEET_MAX_PARALLEL`) and the ticket has no active run.
2. `git fetch` + `git worktree add -b agent/<ref>-<slug> ~/.agent-fleet/worktrees/<run>` from `origin/<base>`.
3. Writes `runs/<run>/prompt.md`, moves the ticket to in-progress, comments the run id.
4. Starts a detached supervisor that runs
   `claude -p --model <tier model> --effort <e>` with stream-json in and out, in the worktree
   (`FLEET_RUN_ID` / `FLEET_TICKET_ID` in env), with a per-tier timeout.
5. When the worker exits, the outcome is recorded: `done` (MR opened), `blocked`, `failed`,
   `timeout`, `no-mr` (exited cleanly without shipping), `stopped`, `taken-over`, or `killed`. Unsuccessful outcomes
   comment on the ticket and send it back to `to-do`.

| Tier | Model | Effort | Timeout |
|---|---|---|---|
| T0 | haiku | – | 20m |
| T1 | sonnet | medium | 45m |
| T2 | sonnet | high | 90m |
| T3 | opus | high | 180m |

Edit `TIERS` in `launch_agent.py` to change the mapping.

## Worker permissions
`FLEET_WORKER_PERMS=allowlist` (default): `acceptEdits` plus the `FLEET_ALLOWED_TOOLS`
list (git, glab, common build/test runners). Any other command is denied, and the worker
must work around it or report blocked. Add your project's toolchain (e.g. `Bash(cargo:*)`) to
that list. `FLEET_WORKER_PERMS=bypass` uses `--dangerously-skip-permissions`; only use it
when the machine is a disposable sandbox.

## Files
`~/.agent-fleet/runs/<run>/` → `meta.json` (state of record), `prompt.md`, `stream.jsonl`
(full transcript), `stderr.log`, `supervisor.log`.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
