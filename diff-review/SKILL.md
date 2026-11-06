---
name: diff-review
description: >-
  Review any changeset adversarially: unstaged or staged changes, a branch, or a
  merge request, so what a later human
  or automated reviewer would raise is found first: you read each change with
  its callers, run the repo's own checks, and walk it through lenses that
  happy-path reviews skip (concurrent and repeated requests, what an empty or
  no-op result means, values traced end to end, rule parity across entry
  points, partial failure, lifecycle states, cost, security, compatibility,
  discoverable inputs, speculative flags, names and structure).
  Each finding is verified on the current head with a concrete failure
  scenario. Use when the user says "review this", "review my diff", "review my
  uncommitted changes", "review what I've staged", "review the branch",
  "review this MR", "peer review", "second pass before I raise it", "what
  would a reviewer find", or "diff-review". Read-only: never edits, comments,
  approves, drafts, commits or pushes.
---

# Diff review

You review a change as a careful outside reviewer would, before they do. A change
can do what its author meant and still be wrong under a second request, another
flag, another way in, or a failure halfway through; look there on purpose. You
report; fixing is `pr-takeover`'s job, gating an open MR is `pr-monitor`'s.

## Ground rules

- **Read-only.** Run checks in the existing checkout or a scratch worktree;
  never edit, switch the user's branch, comment, resolve, approve, mark Draft
  or Ready, commit or push.
- **Review in this session.** Read the diff yourself; no subagents. For a
  second opinion from another agent the user can invoke `pair-programming`.
- **Read the neighbourhood, not the hunk.** Open the callers and callees of
  every changed function; most misses sit one call away.
- **A finding is a failure scenario**: concrete input, state or interleaving →
  wrong result, or a concrete cost to a named reader or maintainer ("adding a
  variant means editing 4 files"), with file:line and a severity. Verify it on the current head
  before you report it.
- **Only rules count.** Style with no repo or user rule and no concrete reader or
  maintainer cost goes on the "not counted" line, never in findings.
- **Unrun is not passed.** A check you couldn't run is reported "not run";
  unmeasured cost is "not measured".

## 1. Scope

Pick the changeset from what the user asked; when they don't say, review
everything not yet on the target: committed, staged, unstaged and untracked.

| Asked for | Diff |
|---|---|
| unstaged changes | `git diff` |
| staged changes | `git diff --cached` |
| all uncommitted work | `git diff HEAD`, plus untracked files (`git ls-files --others --exclude-standard`) |
| the branch | `git diff origin/<target>...HEAD` and `git log --format='%h %s' origin/<target>..HEAD` |
| an MR / PR | its head vs its target (`glab mr diff <iid>`, `gh pr diff <n>`) |

```bash
git fetch -q origin
git status --short          # what is modified, staged, untracked
git diff --stat HEAD; git diff --stat origin/<target>...HEAD
```

Untracked files are new code: read them whole. If a file looks like the user's
unrelated WIP, ask before reviewing it. For an MR, take the target from it
(`glab mr view <iid> -F json | jq -r .target_branch`,
`gh pr view <n> --json baseRefName`). List the touched entry points: routes, CLI
flags, UI, installers and scripts, jobs, migrations, config.

## 2. Run the repo's checks

Derive them from the repo, not memory: the `Makefile`, `lefthook.yml` /
`.pre-commit-config.yaml`, `package.json` scripts, linter and formatter config,
CI config, and every `CLAUDE.md` on the path of a changed file. Run the
formatter, linter, type checker, pre-commit hooks and unit tests for the
changed modules only. A formatter or linter error is a finding.

Then scan the diff for:
- debug leftovers (`console.log`, `fmt.Println` in library code, `print(`);
- commented-out code, or a TODO/FIXME added without an issue;
- secrets or tokens, large or binary files, generated files edited by hand;
- AI attribution in commits or the MR description (`Co-authored-by: Claude`,
  `Generated with`) when the user's rules forbid it;
- breaks of the repo's and the user's `CLAUDE.md` style rules (for example
  one-line comments).

`pr-monitor` and `pr-raise` hold an MR to this same bar.

## 3. Map the change

For each changed function, note in a line or two: callers, callees, what it
reads and writes, the transaction or lock it runs under, and which entry points
reach it. For new files and packages, note how the nearest sibling module lays out
the same job. The lenses run against this map.

## 4. Walk every lens

Don't stop at the first finding.

| Lens | Ask | Counts when |
|---|---|---|
| **Concurrency, repetition** | The same request twice at once (double click, retry); two different requests on one subject at once (two tabs, two clients of one user). What does each read before it writes? | Both can act on the same stale state, or a retry of a success is refused |
| **Empty and no-op results** | Every 0 rows, `false`, empty, not-found or skipped branch: which states produce it? `ON CONFLICT DO NOTHING` returns 0 for every existing row | One signal is mapped to one meaning and a real state gets the wrong answer |
| **Values end to end** | Each flag, setting, header or argument: from where it is set to where it is used. Who sets it, why, and how would they find it? | A callee re-reads env, a global, a cache or a default instead of what it was handed; a required input is read only from an env var, so `--help` doesn't show it (prefer a flag; for a secret, name the trade-off: flags show in process lists and shell history); nothing in the change varies a flag or key, so it should be a constant |
| **Parity across entry points** | Each rule (validation, normalisation, limits, auth): every other way in (API, CLI, UI, each installer, admin tools). Each mode or type value: every place that branches on it | Copies differ; find why before choosing, a stricter copy may guard a fragile downstream writer. The same value is compared in several places (`if env == "a"`, `switch kind`): suggest one type per variant or a data table. A single `if` doesn't count |
| **Partial failure** | Multi-step work outside one transaction: step 2 fails after step 1; a retry; a hint step (stamp, metric, cache, notice) failing | A hint fails the real operation or records one that didn't happen; a retry isn't idempotent |
| **Lifecycle states** | Each lookup: the states its subject can be in (active, suspended, deleted, revoked, expired, pending) vs how the rest of the code filters that table | A deleted or revoked thing still works |
| **Cost** | Cascades, loops over remote calls, N+1, whole rows read for one field, per-request work that could run once; long transactions under a request deadline | Worst case stated in rows or calls; "not measured" with the test that would settle it |
| **Security, tenancy** | Authz on each new path; tenant and identity from the authenticated principal; secrets out of logs, argv, URLs, errors; input quoted for the shell, SQL, file format, plist, registry or template it reaches | Any gap with a concrete exploit or leak path |
| **Compatibility, rollout** | Changed signatures, wire formats, config keys, defaults; an old client, a half-deployed fleet, a rollback; migration reversibility | An old or mixed version breaks, or a migration can't be undone and doesn't say so |
| **What tools let through** | Doc comments above the wrong declaration, import groups, stale comments, comment length vs house rule; build or test steps that grep source text. Read each call site alone: can you tell what happens? Compare the layout with sibling modules (for example a `cmd` package with one file per command and a thin `main`) | A reader is misled, or a grep can be satisfied by a comment; `check`, `Run`, `process` or `handle` hides that the code runs tests, sends mail or deletes data; files exist only because of the order things were added; one file mixes argument parsing, business rules and orchestration |
| **Tests** | Each fix or feature has a test that fails without it (run it red on the old code); concurrent, retried, failure and old-client paths covered; a timing-dependent test waits on a condition, not on which statement blocks | Only the happy path is tested, no test can fail, or a timing test assumes which statement blocks |

To prove a race, hold a lock in a side transaction, start both requests, wait
until both are blocked behind the holder, then release. Count every backend
blocked transitively behind the holder's pid (walk `pg_blocking_pids` from each
waiter in `current_database()`), never waiters filtered by query text: under
other timing the second request blocks on a different statement first.
Sequential tests cannot show one.

## 5. Verify

For each candidate, re-read the cited code on the current head and confirm the
scenario. Run a test if one can show it. Drop what doesn't survive; mark what
you couldn't verify.

## 6. Report

Verdict first, then findings by severity, then what was checked.

```
Review of feat/x vs main (+ uncommitted): 3 findings (1 fix before merge, 2 should fix)

Fix before merge
1. A retried checkout charges the card twice: orders/service.go:88
   Scenario: client times out and retries → second request sees no order yet → two charges
   Verified: read CreateOrder; no idempotency key checked before ChargeCard
   Suggest: key the charge on the request id; test: two concurrent CreateOrder calls, one charge

Should fix
2. `Run` also deletes old releases, which its name hides: deploy/run.go:40
   Scenario: a maintainer adding a retry at the call site can't tell it deletes data
   Verified: read Run and its 2 callers
   Suggest: rename to `RunAndPruneReleases`, or split out the delete

Checks: gofmt, go vet, golangci-lint pass; unit tests pass; integration not run (no TEST_DATABASE_URL)
Lenses with nothing found: parity, compatibility, security
Not counted: 1 naming preference (no rule)
```

Severities: **Fix before merge** for wrong results, data loss or security;
**Should fix** for real but latent or rare problems; **Minor** for unmeasured
cost, placement or wording. A reader or maintainer cost alone is **Should fix** or
**Minor**, never **Fix before merge**.

## Failure modes

- **No target branch or MR found:** for a branch or MR review, ask which branch
  to compare against; never guess `main`. A working-tree review needs none.
- **A check can't run** (missing tool, no database, others' half-done edits break
  the build): report it "not run" with the reason; if only unrelated files break
  the build, run in a scratch worktree at HEAD with the changed files copied in.
- **Diff too large to read whole:** say so, review by module in order of risk
  (auth, data writes, migrations first) and list what you didn't reach.
- **A finding depends on external behaviour** (a vendor API, a tool's parser):
  test it locally if you can, otherwise mark it unverified with what would
  confirm it.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
