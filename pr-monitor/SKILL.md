---
name: pr-monitor
description: >-
  Watch an open merge request / pull request and keep it from being merged
  while it has real problems: new review comments and unresolved threads, CI
  pipeline status and failed jobs, unit test results, code coverage against the
  target branch, merge conflicts, and a diff-review of each new head
  (repo checks, cleanliness, and the adversarial review lenses). Each
  signal is verified before it counts; when a valid issue is found the MR/PR is
  marked Draft so it cannot be merged, and the user gets a short report. Keeps
  the linked ticket's status in step through ticket-manager (in-progress,
  in-review, done on merge to main). Started automatically by pr-raise and
  pr-takeover. Watches run in their own helper agent beside the user's
  session (session-manager), messaging the session only on events; batches a
  reviewer's comments and offers a pr-takeover handoff. Merges the target in on
  its own when it conflicts simply or overlaps the MR (a merge commit, no force push),
  and retargets a stacked MR whose parent merged; on request, syncs
  the branch with main (rebase, conflicts, stacked MRs) and cleans up after a merge.
  Use when the user says "monitor this PR", "watch MR 858", "keep an eye on the
  PR", "pr-monitor", "tell me if CI or review comments need attention", "rebase
  with main", "pull changes from main", "fix the merge conflicts", "first MR is
  merged, update the second", "this is merged, remove the worktree", or runs it
  under /loop to poll an MR. Never merges, resolves threads or replies; pushes only a
  feature branch: a merge of the target, or a sync when asked.
---

# Monitor PR

You gate a merge request (GitLab) or pull request (GitHub): report what changed,
judge whether each signal is a real problem, and if any is, mark it **Draft** so
nobody merges it by accident. Fixing is `pr-takeover`'s job.

## Where it runs

- **One check** ("check MR 881 now"): here, in the calling session.
- **A watch** ("monitor this PR", or started by `pr-raise` / `pr-takeover`): in a
  **monitor helper**, so polling never fills the user's session. Load
  `session-manager` and `start` one:
  - name `mr-<iid>-monitor`, role `monitor`, agent `claude`, labels
    `pair.feature=mr-<iid>`, cwd the repo checkout (a trusted folder, or the
    first message never arrives);
  - first message: `/loop pr-monitor <mr-url> — you are the monitor helper; report events to <session-manager self()>`;
  - one monitor per MR: if `status(mr-<iid>)` shows `mr-<iid>-monitor` live,
    reuse it and say so;
  - first run "Catch-up" below, so an MR that merged while nothing watched it
    is closed out;
  - run Catch-up again on every event from a monitor and when you resume after
    a restart, and "Close-out" as soon as you learn an MR of yours merged or
    closed, from any source;
  - it is a child of the calling session and ends with it.
- **When you are the monitor helper** (your first message says so): on t3, call
  `watch_pull_request` with the MR URL on your first run, and
  `unwatch_pull_request` when you stop the loop. Runs are silent in your pane; send the caller (session-manager `report_command`) only
  these events, one line each, prefixed `mr-<iid> event:`
  - drafted (with the reasons) or looks ready to undraft (the caller asks the
    user and waits for a yes);
  - a review batch settled (see "Peer review comments");
  - ticket moved;
  - the target merged in and pushed ("Merging in the target"), with the new
    head and what each hunk kept; or behind with overlap but not merged, and why;
  - conflicts that aren't simple: offer a sync;
  - parent MR merged: retargeted and the target merged in, or why not
    ("Stacked on a merged parent");
  - merged or closed (the final one); the caller runs "Close-out". Then
    `unwatch_pull_request`, stop the loop, and on t3 settle your own thread:
    `t3_thread_organize` (`settle`, no `threadId`; it applies when your turn
    ends). The caller forgets you on this event (session-manager "Stopping on t3");
  - stuck: auth failure, API errors on two runs in a row, or a blocked dialog.
  The calling session relays them; you never ask the user directly.
- **A `mr-<iid> nudge` from the caller** (a push): run a check now and start the
  new head's review without waiting for its pipeline. A review report it names
  for that sha counts as the review; read it instead of starting a reviewer.

## Ground rules

- **The automatic writes are Draft, the ticket, and retargeting a stacked MR
  whose parent merged.** Drafting on a valid issue, ticket-manager's status moves
  and comments, and that retarget are pre-authorised. Everything
  else outward-facing needs a yes: comments, replying to or resolving threads,
  retrying jobs, editing the description, labels, reviewers.
- **Never** merge, approve or undraft on your own, or push except a requested
  sync ("Syncing with main") or a merge commit of the target
  ("Merging in the target"). Never push to `main` or the target branch.
- **Undraft only on the user's yes for that MR** (`glab mr update <iid> --ready`,
  `gh pr ready <n>`). This binds the calling session too, and a standing "decide
  yourself" doesn't cover it: ask, even when everything else is delegated.
- **Verify before you count.** A comment, red job or coverage dip is a signal,
  not a verdict: read the code, the log, the numbers. Only a verified problem
  drafts the MR.
- Read-only on the working tree unless asked for fixes: run checks in the
  existing checkout or a scratch worktree, never switch the user's branch.

## 1. Snapshot

GitLab (from the repo, or pass a number/URL):

```bash
~/codebase/ai-skills/pr-monitor/scripts/mr-snapshot.sh [<iid>|<url>]
```

It prints one JSON digest: MR state (draft, conflicts, merge status, sha),
unresolved threads and new notes, head pipeline status, failed and running jobs,
unit-test summary, coverage and target coverage. State lives in
`~/.pr-monitor/<project>-<iid>.json` (`PR_MONITOR_DIR` overrides);
`changed_since_last` says what is new.

GitHub equivalents:

```bash
gh pr view <n> --json number,title,url,isDraft,state,mergeable,mergeStateStatus,headRefOid,reviewDecision,statusCheckRollup
gh pr checks <n>
gh api repos/{owner}/{repo}/pulls/<n>/comments      # inline review comments
gh api repos/{owner}/{repo}/issues/<n>/comments     # conversation comments
gh api graphql -f query='...reviewThreads{nodes{isResolved comments{nodes{body path line}}}}...'
```

## 2. Triage each signal

| Signal | Where | Counts as a valid issue when |
|---|---|---|
| **Review comments** | unresolved threads, new notes | Read the code at that path/line on the current head. Valid if true and unaddressed: a bug, a security or data-loss risk, a broken contract, a missing test the reviewer asked for, a request the author agreed to. Not valid: a nit the repo's rules don't back, an answered question, a comment on changed code, or a wrong claim (say why). |
| **CI pipeline** | `pipeline.status`, `failed_jobs` | A failed job with `allow_failure: false` on the head sha; read the log tail (`glab ci trace <job-id>` / `gh run view --log-failed`). A flake (network, runner, timeout with no code cause) is reported, not drafted; retry only with a yes. An old sha's pipeline doesn't count; wait for the current one. |
| **Unit tests** | `pipeline.tests` (GitLab test report), job logs | Any failed or errored test on the head sha. Name the tests. |
| **Coverage** | `pipeline.coverage` vs `pipeline.target_coverage` | Drop of more than 0.5 percentage points against the target, or below a floor the repo declares (Makefile, CI config, `CLAUDE.md`). None reported is not an issue; say it isn't measured. |
| **Merge conflicts** | `mr.has_conflicts`, `merge_status` | Conflicts with the target branch. |
| **Code review** | the MR diff, via `diff-review` in a fresh reviewer | Only when the head sha differs from `review.reviewed_sha` in the state file; see "Reviewing a new head". **Fix before merge** is a valid issue; **Should fix** and **Minor** are reported, not drafted. |

Merge status alone (`not_approved`, waiting for review) is information, not an
issue.

### Reviewing a new head

Each new head gets a **fresh reviewer**: no bias from earlier reviews, and the
monitor's context stays small:

1. `git worktree add --detach ../<repo>-mr-<iid>-review-<n> <sha>`: never the
   user's checkout.
2. session-manager `start(mr-<iid>, reviewer, claude, cwd: that worktree)`, hidden
   (no pane).
   Task: "Load the `diff-review` skill and review `<sha>` against
   `origin/<target>`; write the report to `~/.pr-monitor/<project>-<iid>-diff-<n>.md`."
3. `collect()` its report, then `stop` the reviewer (on t3, session-manager's
   "Stopping on t3", so its thread leaves the sidebar) and
   `git worktree remove --force` the worktree.
4. Record `review: {reviewed_sha, findings, file}` (one-line titles) in the state
   file, so the next run on the same head repeats nothing.

One reviewer at a time: if the head moves during a review, let it finish, then
review the newest head, skipping those between.

A **one check** runs `diff-review` in the calling session directly; it has no
earlier reviews to be biased by.

## Peer review comments

A reviewer usually leaves several comments at once. Judge each, but tell the user
once:

1. **Triage each new note on arrival** (step 2's review row). A verified valid
   one drafts the MR at once: Draft doesn't wait.
2. **Hold the report until the batch settles:** no new note for 10 minutes, or
   the notes came as one submitted review (same author, same `created_at`
   minute). While open, check again in about 10 minutes; keep it in the state
   file as `review_batch: {since, authors, note_ids}`.
3. **When it settles,** write the verified list to
   `~/.pr-monitor/<project>-<iid>-review-<n>.md`: one line per comment with
   author, path:line, verdict (valid / not counted, with the reason) and the
   head sha checked. Then report once:

   ```
   mr-881 event: @sam left 6 comments: 4 valid, 2 not counted. Take over? ~/.pr-monitor/123-881-review-1.md
   ```

4. **Handoff.** On a yes, the **calling session** (not the monitor) loads
   `pr-takeover` with that file: it has the feature context and becomes the only
   agent pushing to the branch. The monitor keeps watching; it doesn't fix, reply
   or resolve.

## 3. Act

- **Conflicts with the target:** first try "Merging in the target". Pushed:
  the conflict is no longer an issue. Not simple: it is a valid issue, as below.
- **Any valid issue and the MR is not Draft:** mark it Draft, then record why.
  - GitLab: `glab mr update <iid> --draft`
  - GitHub: `gh pr ready <n> --undo`
  - Write the reasons into the state file's `draft_reason` (one line per issue),
    so the next run knows this skill drafted it and why.
- **Already Draft:** leave it. If every `draft_reason` issue is resolved, tell the
  user and offer to mark it ready; don't do it yourself.
- **No valid issues:** change nothing.

## 4. Sync the ticket

Every run, after acting (so a new Draft is reflected), load `ticket-manager` and
run its **Sync** step with the MR's state: open/Draft, ready, merged (and into
which branch), or closed. It reads the ticket from the description or the state
file and records what it did there. A tracker failure is reported, never a reason
to skip the rest of the run.

## 5. Report

Lead with the verdict, then only what changed or needs action:

```
MR !858 — drafted (2 valid issues)
- CI: backend-unit failed on 1a2b3c — TestJoinOrg_… (assertion, not a flake): <job url>
- Review: @reviewer on repository.go:142 — rename can collide on retry; verified, unaddressed
Not counted: 1 nit (naming), coverage not reported by this pipeline
Ticket https://kaneo.example/acme/task/ACME-154: in-review → in-progress (commented)
```

## Merging in the target

The one push a run makes on its own, by the monitor helper or a one-off check.
**When:** the MR conflicts with its target, or it is behind and overlaps it:
the target changed, since the merge base, a file the MR also changes
(`git diff --name-only $(git merge-base origin/<target> origin/<branch>)` against
each side), or the forge says it needs a rebase. Behind with no overlap changes
nothing a reviewer sees; only report it, once, past 50 commits behind.
**Not when** a pipeline on the current head is still running, this target head
was already merged in or declined (`target_synced` in the state file), or the
MR is approved and a push resets approvals (GitLab `projects/<id>/approvals`
`reset_approvals_on_push`; GitHub branch protection `dismiss_stale_reviews`):
report "behind with overlap" and let the user decide. Nor when the repo requires
linear history or rebases (`CLAUDE.md`, `CONTRIBUTING`, MR settings).

It adds a merge commit and never rewrites history, so it can't clobber another
pusher: a plain push only fast-forwards, and a rejection means someone pushed.

**A conflict is simple when all of these hold** (a merge with no conflict is
always fine):
- the conflicts are with the MR's own target (not a merged parent MR);
- a few small hunks (about 10 lines a side), in source files: not lockfiles,
  generated files, migrations, or a file deleted or renamed on one side;
- each hunk keeps both intents mechanically, e.g. the MR renamed a call and the
  target changed one of its arguments: keep the new call, with the new argument;
- no hunk changes a signature, API, schema or config key, or needs a judgement
  about which behaviour wins.

Anything else: Draft and offer "Syncing with main", as before.

1. **Scratch worktree at the MR head**, never the user's: `git fetch origin`, then
   `git worktree add --detach <tmp> origin/<branch>`. Note that sha.
2. **Merge** `git merge --no-ff origin/<target>`; resolve each hunk, keeping both
   intents. Any hunk turns out not simple: `git merge --abort`, remove the
   worktree, fall back.
3. **Verify.** Build and test the changed modules; then `diff-review` the merge
   commit (`git diff HEAD^1 HEAD`, the conflict files). A failure or a Fix
   before merge: abandon and fall back, reporting why.
4. **Push** `git push origin HEAD:refs/heads/<branch>`: a plain push, no force.
   Rejected: someone pushed since step 1; abandon and let the next run look again.
5. **Clean up** the worktree, record `target_synced` (the target sha), then send
   the event: the new head, each file and what it kept, test results. Tell the caller to `git pull --ff-only` in the
   branch's worktree before its next commit. The next run reviews the new head.

### Stacked on a merged parent

When the MR's target, now or at the last run (`target` in the state file), is
the source branch of an MR that merged (not closed):
1. **Retarget** to the parent's target, unless the forge already did:
   `glab mr update <iid> --target-branch <parent target>`,
   `gh pr edit <n> --base <parent target>`.
2. **Merge in the new target** ("Merging in the target"), overlap or not: until
   then the diff also shows the parent's commits. Same guards, same fallback.
   After a squash merge, lines the parent added and this MR edited conflict;
   that isn't simple, so it falls back to "Syncing with main" step 3.
3. Record `target`, then send one event: retargeted, merged in (new head), or why not.

## Syncing with main

Only when the user asks or says yes to an offer. A run that finds conflicts that
aren't simple, or a merged parent it couldn't merge in, offers it and never syncs on its own. **The calling session does
the sync, not the monitor helper**, so one agent pushes to the branch, in the
user's worktree.

1. **Check first.** Find the branch's worktree (`git worktree list`). Uncommitted
   changes there: stop and ask. The branch is `main` or the default branch: stop.
2. **Update.** `git fetch origin`, then what the user asked for: "rebase" →
   `git rebase origin/<target>`; "pull" or "merge" → `git merge origin/<target>`;
   unsaid → rebase.
3. **Stacked MR whose parent merged.** Only this MR's commits move:
   `git rebase --onto origin/main <old-parent-tip> <branch>`, then retarget it
   (`glab mr update <iid> --target-branch main`, `gh pr edit <n> --base main`).
4. **Conflicts.** Read both sides and keep both intents. Never `-X ours/theirs` or
   a whole-file pick to get past one. If the two can't both hold, abort
   (`git rebase --abort`) and ask, showing the hunk.
5. **Verify.** Build and test the changed modules. If a conflict changed code, run
   `diff-review` on the result before pushing.
6. **Push the feature branch.** After a rebase `git push --force-with-lease origin
   <branch>`; after a merge a plain push. Never to `main`. Rejected: fetch and
   look; someone else pushed, so don't override it.
7. **Report** the new head, conflicts resolved and test results. The next monitor
   run reviews the new head on its own.

**After a merge,** Close-out removes the worktrees and branches that pass its
check; anything that fails it stays, and removing it needs a yes. A stacked child
MR's monitor handles it ("Stacked on a merged parent"); with no monitor on it, offer step 3.

## Watching over time

A watch is the monitor helper running `/loop pr-monitor` (self-paced) in its own
pane; see "Where it runs". Pace:

- pipeline running or pending: check again in about 5-10 minutes;
- a review batch still open: about 10 minutes;
- looks ready (green, no valid issues) or approved: about 5 minutes, since a
  merge usually comes next;
- idle, waiting on reviewers: about 30 minutes;
- when the MR is merged or closed, sync the ticket one last time (done on a
  merge to main), send the final event, then stop the loop and settle the
  thread (see "Where it runs").

The self-paced wakeup lives in the helper's process: if the harness ends the
process, the next check is lost and nothing reports it. On t3 the
`watch_pull_request` watch survives that and wakes the thread on checks,
comments, reviews and conflicts, but not on a merge. Catch-up covers the merge.
Don't count on T3 settling a linked thread when its PR merges: that is the
user's `sidebarAutoSettleOnMerge` setting, and it may be off.

### Catch-up

List every watched MR that merged or closed and isn't closed out yet:

```bash
~/codebase/ai-skills/pr-monitor/scripts/stale-watches.sh          # list
~/codebase/ai-skills/pr-monitor/scripts/stale-watches.sh --sync   # list and sync their tickets
```

One JSON line per MR (GitLab only); `--sync` runs ticket-manager's **Sync** for
each ticket not already synced to the final state. Run "Close-out" for each.

### Close-out

The calling session's job, for each MR that merged or closed, however it learned
(the final event, Catch-up, a linked PR's state, the user):

1. **Ticket:** `stale-watches.sh --sync` (done on a fixes MR merged to main).
2. **Monitor and reviewers:** every helper in `$SM status --feature mr-<iid>`:
   session-manager "Stopping on t3" (settle the monitor, archive reviewers),
   then `$SM forget`. Forget force-removes the helper's worktree, so run the
   worktree check (step 4) on it first; a failed check keeps the helper.
3. **The feature's pair helper:** if no other open MR of yours uses it, end it
   (pair-programming "End a feature"; a merge needs no question). Otherwise
   keep it and say which MR still does.
4. **Worktrees and branches,** without asking, when merged (not closed): the
   helpers' and the MR branch's own. For each, after `git fetch origin
   <target> merge-requests/<iid>/head` (GitHub: `pull/<n>/head`), it is safe when
   both hold:
   - `git -C <worktree> status --porcelain` prints nothing;
   - its `HEAD` is in the target (`git merge-base --is-ancestor HEAD
     origin/<target>`) or, after a squash merge, in the MR head
     (`git merge-base --is-ancestor HEAD <head_sha>`, `head_sha` from Catch-up).

   Safe: `git worktree remove <path>`, then `git branch -D <branch>`. `-D`
   because `-d` judges against the local HEAD (wrong in a bare clone); the
   check above is the guard. Not safe: keep it and say why.
5. `stale-watches.sh --mark <watch>`, then one line to the user, e.g.
   `!42 merged: ACME-1 → done; monitor settled; pair helper ended; 3 worktrees removed`.

**Heartbeat**, so a ticket moves even when no agent is alive: a user cron or
launchd job running `stale-watches.sh --sync` every 5 minutes. Set it up only
on the user's yes; without it, Close-out waits for the next event or resume.

Each run is one snapshot plus triage; the state file keeps runs from repeating.
Report only what is new unless the user asks for the full picture.

## Failure modes

- **No glab/gh auth:** say so and stop; `glab auth status` / `gh auth status`.
- **API errors or a missing pipeline:** report the gap; never treat "unknown"
  as "passing" or as a valid issue.
- **Draft fails** (permissions): report the valid issues anyway and say the MR
  could not be drafted.
- **Rebase stops part-way and can't be finished:** `git rebase --abort`, so the
  branch is exactly as it was; report the conflict.
- **Conflict resolution abandoned** (not simple, red tests, a Fix before merge,
  a rejected push): nothing was pushed; Draft and offer the sync as before, with
  the reason.
- **Head moved during the run:** re-snapshot before drafting, so you never draft
  on findings for an old sha.
- **Monitor helper exits or is killed:** the calling session gets the exit
  notice, when there is one; say the watch stopped and offer to restart it. A
  process ended by the harness gives no notice; Catch-up finds those. State on disk means a
  restart repeats no reports.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
