---
name: pair-programming
description: >-
  Work on a feature with a helper agent beside the main session, so the main
  session's context stays small: a long-lived helper for research and tests, a
  fresh reviewer for each review, any agent type (Claude Code by default, Codex
  on request). Runs through session-manager. Use when the user says "start
  feature X with a helper", "pair session", "pair programming", "get codex to review this", "have
  the helper research Y", "write tests for this in the helper", "second
  opinion on this diff", "get it reviewed with helper and push", "fix, get peer
  reviewed and push", or "pair-programming". The one sanctioned way to hand a
  review or research to another agent.
---

# Pair programming

The main session (you) does the feature. Helpers do the side work: reviewing,
researching, writing tests. Only their verdicts come back. Everything runs
through `session-manager`; load it first.

## Ground rules

- Delegate only when this skill is invoked. Otherwise review and research
  yourself, in this session (the user's standing rule: no subagent fan-out).
- Helpers never run in the user's working tree: the helper gets its own
  worktree, each reviewer a detached one.
- Helpers never commit, push or start other agents.
- Only you talk to the user. Relay a helper's question; never answer it with a
  guess on the user's behalf.

## Start a feature

When the user starts a feature with a helper:

1. Name the feature: a short slug from the request (`csv-export`).
2. Start the long-lived **helper** (role below) with session-manager, agent
   `claude` unless the user names another. Its first task: "Read the repo's
   CLAUDE.md files for <module>; wait for tasks."
3. Tell the user it is running in the pane to the right, and how to address it
   ("helper: research X", "codex review", "tests for Y").

Reviewers are not started up front; one is started per review.

## Roles

| Role | Lifetime | Where | May edit | Its rules (sent in the envelope) |
|---|---|---|---|---|
| **helper** | whole feature, reused | own worktree | yes, in its worktree | Do the task as scoped. Tell me which files you changed. |
| **researcher** | the helper, given a research task | helper's worktree | no | Primary sources only (vendor docs, source code, changelogs) with URLs and the date read. Separate verified facts from inference. |
| **tester** | the helper, given a test task | own worktree | tests only | Write and run tests for the scoped behaviour; prove each can fail. Report the commands and their results. |
| **reviewer** | one review, then stopped | detached review worktree | no | Review the diff given. Findings only: file:line, the defect, a concrete failure scenario, severity. No style opinions the repo's rules don't back. Say what you didn't check. |

A fresh reviewer per review means no bias from earlier tasks; a long-lived
helper keeps the feature's context and is cheaper.

### The helper's worktree

```bash
git worktree add ../<repo>-<feature>-helper -b <current-branch>-helper HEAD
```

Next to the user's other worktrees (the repo is a bare clone). It starts from
**committed** HEAD, so a task needing uncommitted work gets a patch
(`git diff > ~/.agent-sessions/<feature>/wip.patch`, applied in the worktree).
Its changes come back as files you read and bring over with the user's yes; never
merge its branch into the user's on your own. Remove the worktree when the feature
ends (`git worktree remove`), after asking.

## Delegating

- **Review:** write the diff scope (`git diff origin/<target>...` plus
  uncommitted changes) to `~/.agent-sessions/<feature>/review-<n>.patch`, then
  give the reviewer its own tree at the commit under review:

  ```bash
  git worktree add --detach ../<repo>-<feature>-review-<n> <sha>
  git -C ../<repo>-<feature>-review-<n> apply ~/.agent-sessions/<feature>/review-<n>.patch  # only for uncommitted work
  ```

  `start(feature, reviewer, agent, cwd: that worktree)` with the patch
  named in the task. Once its result is collected, stop the reviewer and
  `git worktree remove --force` its worktree (it is scratch; this skill made it).
- **Research / tests / other:** `delegate(helper, task)` to the long-lived
  helper with the role's rules in the envelope.
- Keep working while helpers work. Collect with `collect()` when you need the
  result or a report arrives.

## Review and push

"Get it reviewed and push" is one request; the ask is the yes to push:

1. Commits only: uncommitted work isn't pushed. Ask whether to commit it first.
2. Run a **Review** (above) on the unpushed commits, with a fresh reviewer that
   loads `diff-review` and reports its severities.
3. Verify each finding against the code, as in "Bringing results back".
4. **No verified "Fix before merge" finding:** push the feature branch (never
   `main`) and report the commit, plus any "Should fix" or "Minor" findings.
5. **Otherwise don't push.** Show the findings. If the user said "fix" too, fix
   them and review again, at most twice, then stop and ask.

**After any push to a branch with an open MR** (this flow or any other), nudge
its monitor if `$SM status --feature mr-<iid>` lists `mr-<iid>-monitor`:
`$SM delegate mr-<iid>-monitor` with `mr-<iid> nudge: pushed <sha>`, plus the
review report's path when step 2 covered that sha. It reviews the new head at
once instead of on its next timed check.

## Bringing results back

Per result, tell the user in at most three lines: the verdict, what you will do
with it, and the file path. For a review, verify each finding against the code
before fixing it; list the ones you reject and why.

## End a feature

On "done with the feature" (or the user closing it): list the feature's helpers
(`status`), ask, then `stop` each and offer to remove the helper worktree. When
pr-monitor's Close-out finds the feature's last open MR merged or closed, end
them without asking and say so.
Result files in `~/.agent-sessions/<feature>/` stay.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
