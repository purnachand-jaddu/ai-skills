---
name: ship-mr
description: Final step for a fleet worker agent — verify the work, commit, push the branch, and open a GitLab merge request linked to its ticket; or mark the run blocked when a human decision is needed. Use when a worker has finished implementing its ticket, or cannot proceed.
---

# Ship an MR (worker side)

You are inside a fleet worktree; `FLEET_RUN_ID` is set. Paths below are exact.

## 1. Verify before shipping
- `git diff origin/<base>...HEAD --stat` — every change belongs to this ticket; no stray
  debug code, generated junk, or secrets (`.env`, keys, tokens).
- Run the repo's checks if present (look at `package.json` scripts, `Makefile`, `pyproject.toml`,
  CI config): tests, lint, typecheck. Fix what you broke. If a check was already failing on
  the base branch, say so in the MR rather than "fixing" unrelated code.
- Everything committed: `git status --porcelain` is empty. Use conventional commit messages
  (`fix(api): …`, `feat(web): …`) that match the repo's history (`git log --oneline -10`).

## 2. Open the MR

Pass the description on stdin (don't write it to a file in the worktree — that would make
it dirty):

```bash
python3 ~/codebase/ai-skills/ship-mr/scripts/ship.py mr \
  --title "<conventional title, ≤72 chars>" --body-file - [--draft] <<'MR'
## What
<1–3 sentences: the change, in reviewer terms>

## Why
<the ticket's problem; quote acceptance criteria if any>

## How to verify
- <commands run and their result, e.g. `npm test` → 214 passed>
- <manual check a reviewer can do>

## Notes
<risks, follow-ups, anything you weren't sure about — or "None">
MR
```

Use `--draft` when tests could not be run, a check still fails, or you made a judgment call
the reviewer must confirm. The script pushes, runs `glab mr create`, records the MR URL on
the run, comments it on the ticket, and moves the ticket to in-review. It prints the
URL. Your final message should be that URL plus a two-line summary.

## Blocked instead

If the ticket can't be done correctly without a human (ambiguous requirement, missing access,
conflicting instructions, would require a risky decision):

```bash
python3 ~/codebase/ai-skills/ship-mr/scripts/ship.py blocked --reason "<specific question or missing thing>"
```

Then stop. Don't open a speculative MR. Partial commits stay on the branch for whoever picks it up.
