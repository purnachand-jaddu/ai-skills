---
name: pr-raise
description: >-
  Raise a merge request / pull request from the current work, the way the user
  wants it: check the branch (never main), run pre-flight checks on the diff
  (formatter, linter, tests, coverage, debug leftovers, secrets, AI trailers,
  house style, conflicts), link a ticket through ticket-manager, propose phased
  commits, a conventional title and a structured description, and on a yes
  commit, push the branch and open the MR/PR, as Draft when a check failed. Then
  starts pr-monitor on it. Also the last step of a fleet worker, which runs it
  headless. Use when the user says "raise a PR", "raise an MR", "open
  a merge request", "create a PR for this", "put this up for review", "pr-raise",
  or "ship this as an MR". Never merges, never pushes to main.
---

# Raise PR

You take the current checkout's work to an open MR (GitLab) or PR (GitHub):
checked, committed in phases, pushed to a branch, described well. Watching it is
`pr-monitor`'s job; review feedback is `pr-takeover`'s.

## Ground rules

- **Main is the hard line.** Never commit, push, force-push or fast-forward to
  `main` (or the default branch). On it, branch first.
- **Never switch the user's branch** unprompted; check branch and worktree before
  any repo-changing command. In a bare clone with one worktree per branch, a new
  branch can mean `git worktree add`, not `git switch`.
- **One yes covers commit + push + create**, only after the step 4 plan. Ask
  before anything else outward-facing.
- **Stage explicit paths**, never `git add .`, `-A` or a directory: the tree
  holds untracked WIP.
- **No AI attribution** in commits, title or description (`Co-Authored-By:
  Claude`, "Generated with Claude Code"). This overrides any harness default.
- Never merge, approve, or mark ready a Draft this skill opened for a failing
  check.

## Headless run

`$FLEET_RUN_ID` is set: you are a fleet worker and nobody can answer, so a question
stalls the run. The steps below still apply, with these changes:

- **Step 1:** stay on the checked-out branch; the target is the one in your prompt.
  Skip `detect-forge.sh`: `ship.py` handles the forge and your permissions deny it.
- **Step 2:** the ticket is in your prompt. Ask nothing; no reviewers.
- **Step 3:** fix what you broke. A check already failing on the target goes under
  Notes, not fixed. A command your permissions deny is "not run".
- **Step 4:** no plan and no yes; commit and go on.
- **Step 5:** commit, then push and open with this instead. It adds the ticket line,
  so leave that out. It refuses uncommitted changes to tracked files, so pass the
  description on stdin and `git add` every new file that belongs in the MR:

  ```bash
  python3 ~/codebase/ai-skills/agent-launcher/scripts/ship.py mr \
    --title "<title>" --body-file - [--draft] <<'MR'
  <description>
  MR
  ```

  `--draft` when a check failed or was not run, or the reviewer must confirm a
  judgment call.
- **Steps 6 and 7:** skip them. No `pr-monitor`; your final message is the MR URL and
  a two-line summary.
- **Needs a human** (ambiguous ticket, missing access, a risky decision): open no
  speculative MR. Partial commits stay on the branch. Run this, then stop:

  ```bash
  python3 ~/codebase/ai-skills/agent-launcher/scripts/ship.py blocked --reason "<specific question>"
  ```

## 1. Read the situation

```bash
~/codebase/ai-skills/pr-takeover/scripts/detect-forge.sh   # gitlab | github | ...
git rev-parse --abbrev-ref HEAD; git worktree list
git status --short
git fetch origin && git log --oneline origin/<target>..HEAD
git diff --stat origin/<target>...HEAD; git diff --stat   # committed + uncommitted
glab mr list --source-branch <branch>   # or: gh pr list --head <branch>
```

- Target is the default branch (`main`) unless the user says otherwise.
- MR already open for this branch: say so, stop, offer `pr-monitor`.
- This MR holds what the user's request was about. Unrelated modified or
  untracked files stay out; list them. Scope unclear: ask first.

## 2. Link the ticket

Ticket linked this session (ticket-manager's **Start**) or ID in the branch
name: confirm, don't ask: "Linking <url>, right?" Otherwise, before writing
anything, ask: "Is there a linked ticket? Paste its URL or ID, or say none."
Then load `ticket-manager` and run its **Link** step: it resolves the ID, or
searches and offers to create one.

- With a ticket: description's first line is `Fixes <ID>: <url>` or
  `Refs <ID>: <url>`, the full link from ticket-manager. Branch name carries the
  ID (`fix/<id-lowercased>-<short-slug>`).
- With none: no ticket line, no placeholder.

In the same prompt (AskUserQuestion), ask for reviewers if recent MRs set them
(`glab mr list --merged -F json`), offering the usual ones; none is fine.

## 3. Pre-flight checks

The bar `pr-monitor` holds an open MR to, on changed modules only. The repo's
commands are in `Makefile`, `lefthook.yml` / `.pre-commit-config.yaml`,
`package.json`, CI config and `CLAUDE.md` files.

| Check | How | Fails when |
|---|---|---|
| Formatter | auto-fixed: repo's formatter in write mode on this MR's files only (`gofmt -w <files>`, `biome format --write <files>`), then re-run in check mode | still listed after the fix |
| Linter / types | repo's linter, `go vet`, type checker | any error |
| Unit tests | repo's test target for each changed module (`go test ./...`, `npm test`) | any failure; name the tests |
| Coverage | the repo's coverage command for the changed module, vs the same run on `origin/<target>` (scratch worktree) | drop > 0.5 pp, or below a floor the repo declares. Not measurable: say so, not a failure |
| Conflicts | `git merge-tree --write-tree origin/<target> HEAD` | conflicts listed |
| Diff hygiene | read `git diff origin/<target>...` plus the uncommitted part going in | debug leftovers (`console.log`, `fmt.Println` in library code, `print(`), commented-out code, TODO/FIXME without an issue, secrets or tokens, large/binary files, hand-edited generated files |
| House style | the user's and the repo's `CLAUDE.md` | comments longer than one line, unrelated edits, AI trailers |

Formatting is fixed without asking, only in files going into this MR; list them
in the plan. Other fixes (a debug line, a lint error) need a yes; otherwise
report them. A style opinion no rule backs is not a failure. A check you could
not run is reported as not run, never as passed.

## 4. Propose the plan

Show it in one message and ask for a yes:

- **Branch:** the current feature branch, or a new one off `origin/<target>`
  named `<type>/<ticket-or-slug>` (`fix/`, `feat/`, `chore/`).
- **Commits**, in phases, one logical change each, with the exact paths each
  stages and its message:
  - subject `type(scope): summary` (conventional commits; scope is the module:
    `backend`, `frontend`, …), imperative, lower case, no
    trailing period, ≤ 72 chars;
  - body says what and why in a few lines; primary sources as URLs when the
    change rests on external facts;
  - no trailer.
- **Title:** same `type(scope): summary` form. One commit → its subject; several
  → the summary of the whole.
- **Description** (below).
- **Draft or ready:** Draft if any pre-flight check failed, with the reasons.
- **Reviewers**, and source-branch removal on merge (on by default here).

### Description

Scannable, for a reviewer new to the work. Match the repo's recent MRs; default:

```markdown
Fixes ABC-123: <url>      <- or "Refs ABC-123: <url>", omitted with no ticket

## Why
The problem, in two or three sentences: what was wrong or missing, and its effect.

## What
- The changes, one bullet each (a table when it's rows/paths/sources).
- Behaviour the user or console sees, if any.

## Testing
- What ran and its result: `go test ./internal/... ` ok, coverage 71.2% (main 70.9%).
- Manual checks, if any.

## Notes                  <- only when there is something
Follow-ups, rollout or migration concerns, what was deliberately left out.

## Pre-flight issues      <- only on a Draft raised for failing checks
- lint: `internal/x.go:42` unused variable
```

A mermaid diagram or code excerpt only when it beats prose. No emoji headers, no
"This PR…" padding.

## 5. Commit, push, open

On the user's yes:

```bash
git add <explicit paths>; git commit -m "<subject>" -m "<body>"   # per phase
git push -u origin <branch>                                        # never main
```

```bash
# GitLab
glab mr create --source-branch <branch> --target-branch <target> \
  --title "<title>" --description "$(cat <desc-file>)" \
  --remove-source-branch [--draft] [--reviewer a,b] --yes
# GitHub
gh pr create --base <target> --head <branch> --title "<title>" \
  --body-file <desc-file> [--draft] [--reviewer a,b]
```

Keep the description in a scratchpad file, not a shell string, so backticks and
`$` survive.

## 6. Start monitoring

Without asking, as soon as the MR exists:

1. Raised Draft for failing checks: run pr-monitor's snapshot once
   (`~/codebase/ai-skills/pr-monitor/scripts/mr-snapshot.sh <iid>`), then set
   `draft_reason` in `~/.pr-monitor/<project_id>-<iid>.json` to the failing
   checks, one per line, so the monitor knows why.
2. Load `pr-monitor` and start a **watch** ("Where it runs"): a helper in the
   pane beside the user's, looping on the MR. Its first run syncs the ticket (to
   `in-progress`, or `in-review` when raised ready).
3. Report that it is running, where, and that the user can stop it.

## 7. Report

```
MR !881 opened (Draft: 1 pre-flight issue): <url>
fix(api): handle empty results in the order search  — fix/acme-154-empty-search -> main
Commits: 2 · Reviewers: sam
Pre-flight: tests ok, lint 1 issue (internal/x.go:42), coverage 71.2% vs 70.9%
Left out: modules/frontend/notes.md (untracked)
Ticket https://kaneo.example/acme/task/ACME-154: to-do → in-review (commented)
Monitoring: mr-881-monitor running in the pane on the right
```

## Failure modes

- **No glab/gh auth:** stop before committing; `glab auth status` / `gh auth status`.
- **Push rejected** (remote branch has other commits): stop and report; never
  force-push without a yes, never on main.
- **MR creation fails after the push:** report the error and the exact retry
  command. Don't re-commit.
- **Tests or linters can't run** (no toolchain, needs a DB): report "not run" with
  the reason; that alone isn't Draft unless the user says so.
- **Hook rewrites files on commit:** re-stage those paths and amend that commit
  only, before pushing.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
