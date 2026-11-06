---
name: pr-takeover
description: >-
  Take over an open pull request / merge request and drive it to production
  ready: collect every review comment and thread, verify each against the code,
  fix what's right, push back on what's wrong, run an independent
  production-readiness review, get CI green, and draft replies — without merging.
  Works on GitHub, GitLab, Bitbucket, Gitea/Forgejo, Azure DevOps or plain git.
  Use this whenever the user says "take over PR #12", "address the review
  comments on this MR", "fix the PR feedback", "get this PR ready to merge",
  "make this MR production ready", "resolve the comments on <PR URL>", or hands
  you a PR/MR link or number and wants it finished — even if they don't say
  "takeover". Starts pr-monitor on the PR when done.
---

# PR takeover

You inherit someone's PR (often the user's own) and finish it: every reviewer comment answered with a fix or a reason, an independent review for what reviewers missed, tests and CI green, ready for a human to merge. You never merge.

The hard part is not losing a comment, not "fixing" a reviewer's mistaken claim, not silently making the author's decisions, and not leaving the branch worse than you found it. The workflow exists for those four.

## 0. Ground rules

- **Never merge, never push to the base/default branch, never force-push a branch you didn't create** unless the user explicitly says so for this PR. The human merges.
- **Outward-facing actions need a yes.** Pushing to the PR branch is the job. Replies, resolving threads, PR description edits, reviewers and labels go to the user as drafts first unless they already said "post them" / "resolve them".
- **Repo instructions win.** Read `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, PR templates and lint/format configs before touching code; match the repo's commit style, comment density and test idioms.
- **Reviewers can be wrong, and so can you.** Every comment is a claim to verify against the code, not an order.

## 1. Identify the PR and the forge

Accept a number, URL, branch name, or nothing (then use the PR for the current branch).

Run `scripts/detect-forge.sh` from the repo; it prints the forge (`github`, `gitlab`, `bitbucket`, `gitea`, `azure`, `unknown`), host, path and installed CLIs. Read the matching section of `references/forges.md` for the exact commands. CLI missing or unauthenticated: say which command fixes it (e.g. `! gh auth login`), don't guess an API shape. Unsure a flag exists: check `--help`; CLIs drift.

If nothing works (no CLI, no token, unknown host), ask the user to paste the comments and continue from the branch alone.

## 2. Snapshot everything into a workspace

Make a scratch workspace outside the repo (the session scratchpad, or a temp dir) and save:

- `pr.json`: title, body, author, state, draft flag, base branch, head branch, head SHA, whether it's from a fork and whether maintainers may push to it, mergeability, CI status.
- `comments.json`: **all** feedback, paginated: top-level comments, review summaries (approve / request changes, with bodies), and inline threads with path, line, resolved/outdated state and every reply. Inline threads usually live in a different endpoint from general comments; fetching only one is the commonest way to drop feedback.
- `ci.txt`: the failing checks and the relevant log excerpts.
- `diff.patch`: `git diff <merge-base>..<head>`.

Files keep your context small and let a reviewer helper read the same inputs.

## 3. Check out in isolation

Don't disturb the user's working tree. Create a worktree (`git worktree add --detach <path>`) and check out the PR inside it with the forge CLI, so the branch tracks the right remote (matters for forks). Record `BASE_SHA` (merge-base) and `START_SHA` (PR head): every later diff and review is relative to them.

A fork you can't push to: stop and tell the user. The options are asking the author to allow maintainer edits, or a follow-up branch/PR on top. They choose.

Run the full test suite and linters once before changing anything, so inherited failures aren't mistaken for your regressions.

## 4. Build the ledger

Create `ledger.md` in the workspace: one line per item with a stable id, source, location and status. It's your memory if context gets compacted; trust it over recollection.

Sources, in order:

1. **Every unresolved human comment and thread,** including review summaries that request changes. Resolved threads are context only; outdated ones count if the concern still applies.
   **A pr-monitor review file** (`~/.pr-monitor/<project>-<iid>-review-<n>.md`, handed over by the monitor): seed the ledger from it. Its verdicts were checked on the sha it names; re-check only items whose files changed since.
   **Reviews off the forge count too:** a review file the user points at, findings from earlier in the conversation, notes pasted into chat. A PR with zero forge comments may still have a full review waiting.
2. **Bot and CI feedback indicating a real defect:** failing checks, static analysis, security scanners. Skip noise (coverage-percentage bots, "thanks for the PR"), but note that you did.
3. **An independent production-readiness review** of the whole PR diff by a fresh reviewer with no stake in the code: one helper per takeover, through `session-manager`. Start it hidden in its own detached worktree (`start --feature pr-<n> --role reviewer --cwd <repo> --hidden --worktree-from START_SHA`), with an envelope telling it to load `diff-review` and review `START_SHA` against `BASE_SHA`. Point it at `diff.patch`, `pr.json` and `references/production-readiness.md` by absolute path; the checklist adds areas to cover, `diff-review`'s severities apply. Every finding needs file:line and a concrete failure scenario. `collect()` the report, then stop the helper. If `session-manager` is unavailable, run `diff-review` in this session and tell the user the review wasn't independent. Never spawn a subagent or use one-shot `codex exec`.
4. **The PR description's own claims** ("tested on X", "handles Y"): verify the load-bearing ones or mark them unverified.

## 5. Triage every item

Read the code each item touches, then give it exactly one verdict:

- **fix**: the claim is correct and the fix is within the PR's scope.
- **already addressed**: the current code handles it. Cite the file:line or commit.
- **decline**: the claim is wrong, or the change would make things worse. Give evidence (a test, a doc link, a code path): a reviewer deserves a reason, not silence.
- **needs human**: anything that is the author's or owner's call:
  - adding or removing a dependency;
  - changing an API contract, a schema/migration, or user-visible behaviour;
  - security behaviour;
  - a finding that conflicts with what the PR description or plan explicitly chose;
  - a choice between two reasonable designs;
  - large scope expansion.

  Batch all needs-human items into **one** question, each with the options, your recommendation and why.
- **out of scope**: valid but belongs in a separate PR or issue. Propose the follow-up; don't do it.

Minor findings from your own review: fix the cheap ones in code the PR touched, list the rest. Don't gold-plate.

## 6. Fix

- **One logical change per commit**, in the repo's style, referencing the comment or finding when the repo does. No AI-attribution trailers unless the repo's convention asks for them.
- **For bugs, write the failing test first**, see it fail, then fix. For behaviour changes, test the behaviour, not the implementation.
- **Fix root causes.** If a comment points at one caller, check the other callers of the same function.
- Keep the diff surgical: no drive-by refactors, reformatting or renames no comment asked for.
- Tests must be hermetic: never touch the real user's home config, credentials or global state. Point HOME/XDG/config dirs at temp dirs.
- Run the relevant tests after each fix. Before pushing, run the full suite, the linters/formatters and the build for every target the repo ships. Editor diagnostics can be stale; trust the build.

If a fix turns out to need a human decision, stop and ask; don't improvise.

## 7. Re-review the fix diff

Give `git diff START_SHA..HEAD` and the ledger to a fresh reviewer (not the one that wrote the fixes): a new hidden helper each round, started and stopped as in step 4, on a detached worktree at `HEAD`. Ask for a verdict per ledger item (addressed / not addressed / regressed) and any **new** Fix before merge / Should fix breakage in the fix diff only. If `session-manager` is unavailable, do this in this session and say so in the report.

Loop fix → re-review until clean, up to about 3 rounds. Anything still open then needs a human or a different approach: escalate it with your analysis rather than grinding.

## 8. Push and get CI green

Push to the PR's head branch (a normal push; rebase/force only with the user's OK). Watch CI to completion. If a check fails:

- read the log;
- if it's yours, fix it;
- if it's a flake, prove it (a rerun, plus the reason) before calling it one;
- if it's pre-existing on the base branch, say so with evidence.

"Pushed" is not "done"; green CI on the final SHA is.

## 9. Draft the replies

For each thread, draft a short reply:

- **fixed**: what changed, plus the commit SHA;
- **already addressed**: where, plus the evidence;
- **declined**: the reasoning, polite and specific;
- **needs human**: the question now with the owner.

Draft a PR description update too if scope or behaviour changed (new limits, removed claims, follow-ups).

Save the drafts in the workspace and show them to the user. Post them, and resolve the threads you fixed, only once the user says to. Leave declined and needs-human threads unresolved for the reviewer.

## 10. Report

End with a short report:

- **Verdict:** ready to merge / ready after the listed human decisions / blocked (why).
- **Final head SHA and CI status.**
- **Per item:**
  - fixed (commit),
  - already addressed,
  - declined (one-line reason),
  - needs human (question plus recommendation),
  - out of scope (proposed follow-up).
- **Verification you actually ran:** commands and results. Also what you could not verify, e.g. "not tested on Windows", "live integration not run".
- **Risks that remain**, and what would justify revisiting them.

Then, without asking, load `pr-monitor` and start a **watch** on this PR (a monitor
helper beside the user's pane; it also syncs the linked ticket). If one is already
running (it handed this takeover over), keep it. Say in the report that it is running.

Clean up: remove the worktree once the user no longer needs it. Keep the workspace (ledger, drafts) until the PR merges.

## When to stop and ask

- The PR is from a fork you can't push to.
- A needs-human item blocks other work.
- CI needs secrets or infrastructure you don't have.
- The base branch moved in a way that requires a rebase with conflicts.
- A comment asks for something destructive (data migration, history rewrite).
- After about 3 review rounds an item is still open.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
