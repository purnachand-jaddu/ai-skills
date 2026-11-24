---
name: pr-verifier
description: >-
  Verify that a pull request / merge request works, with evidence: run the
  change where a user meets it (UI, CLI, API, an agent on a VM) instead of
  trusting unit tests, in three stages: setup (start the stack and get the data
  into the right state), drive (use each flow on its real surface) and check (a
  fresh checker reads only the evidence and looks for cheating and defects).
  Follows the repo's own `verify` skill, read from the target branch, and
  offers to draft one when the repo has none. Reports one verdict per head
  with per-flow screenshots and logs, and offers to lock each hand-verified
  flow in as a repeatable case. Use when the user says "verify this PR",
  "verify MR 1080", "e2e this MR", "prove it works", "does this actually work",
  "test it end to end", or "pr-verifier". Never edits the code, pushes, posts
  or changes Draft state.
---

# PR verifier

A review reads the change; this runs it. The question is "does the change work
for the person who meets it", answered with evidence someone else can check.

## Ground rules

- **Meet the change at its surface.** A web page in a browser, a CLI in a
  terminal, an API over HTTP, an endpoint agent on a machine of the right OS.
  A unit test or a direct function call is not verification; when the surface
  can't be reached, say so and mark the flow not verified.
- **The judge comes from the target branch.** Read the repo's verify skill
  from `origin/<target>`, never from the PR: a change that can edit its own
  check makes the check worthless. A PR that changes the verify skill is
  verified with the target's copy, and the report says so.
- **Isolated and disposable.** Every run gets its own stack (the repo skill
  says how), never the user's dev stack, and leaves nothing running that it
  started unless the user asked to keep it.
- **Read-only towards the PR.** No edits, commits or pushes, and never a
  Draft change: that stays pr-monitor's. Posting the evidence or a comment
  needs the user's yes.
- **No retry until green**, no added sleeps. A flaky step is reported as
  flaky with what was seen each time.

## 1. Target

The PR/MR as given (number, URL or branch); none given, the one for the
current branch. Collect: head sha, target, the diff's paths, the description,
and the linked ticket's acceptance criteria (ticket-manager) when there is one.
Work in a detached worktree at the head sha, never the user's checkout.
`<feature>` is the caller's, else `verify-<number>`; `<n>` is the next free
number under `~/.agent-sessions/<feature>/`.

## 2. The repo's verify skill

```bash
git ls-tree -r --name-only --full-tree origin/<target> -- .agents/skills .claude/skills | grep -E '(^|/|-)verify/SKILL\.md$'
d=$(dirname <that path>); rm -rf "<worktree>/${d:?}"    # replace the head's copy, scripts included
git archive origin/<target> "$d" | tar -x -C <worktree>
```

The worktree now holds the target's whole skill folder, so the helpers that
start there load the target's skill and run the target's scripts. When the PR
changed that folder, the report says its changes were not used.

- **Found:** follow it for setup, drive and check; it overrides the defaults
  below wherever it speaks.
- **None:** say so in one line, and offer to draft one from
  `templates/verify-SKILL.md` for the user to commit. Without it, run the
  defaults below and label the verdict **weak evidence**: the steps were
  guessed, not the repo's.

## 3. Plan the flows

1. **Flows:** each acceptance criterion and each behaviour the description
   claims becomes a flow: a start state, the user's actions, the visible
   outcome. Name flows the change touches that nobody claimed, too.
2. **Checklist:** add the repo skill's checklist items whose trigger matches
   the diff (most runs match a few, not all).
3. **Surface and environment** per flow, from the repo skill's surface map.
4. **No flow at all** (no criteria, no claims, no checklist match): stop and
   ask the user what the change should do; never report a run with nothing
   in it.
5. Show the plan as a table (flow, surface, environment, how it's driven) in
   one message, then go on; ask first only when a flow needs something
   outward-facing (a shared environment, a real account, money).

## 4. Setup and drive

Start one **verifier** helper (session-manager, role `verifier`, in the
worktree from step 1) with the plan and the repo skill:

- **Setup:** the repo skill's setup, with its shortcuts (seeded users, minted
  tokens, fixtures) to reach each flow's start state.
- **Drive:** each flow on its surface, the way a user would: clicks and typing
  in the browser, commands in the terminal, real requests. No script that
  sets the end state directly.
- **Evidence** per flow, into `~/.agent-sessions/<feature>/verify-<n>/<flow>/`:
  `before.png` and `after.png` (or the terminal output) and a `steps.md` of
  what was done, in order, with timestamps; plus the logs the repo skill names.
- Defaults with no repo skill: build the change, start what its README or
  compose file starts, drive each flow, capture the same evidence.

Independent flows may run in parallel only on separate stacks, and only as
many as the machine holds; the repo skill says how many.

## 5. Check

A fresh **checker** (role `checker`, read-only, `--hidden`) gets only the plan
and the evidence folder, not the verifier's account of it. For each flow:

- **Driven for real?** The steps reach the outcome through the surface; a
  step that set state behind the UI's back, called the function directly or
  skipped the action fails the flow.
- **Evidence matches the claim?** The after-screenshot or output shows the
  outcome, not a login screen, an error page or yesterday's state.
- **Defects** seen on the way, even when the flow passes: wrong text, a
  button that does nothing, a layout broken at narrow width, a slow step.

It writes `pass`, `fail`, `not verified` (and why) or `flaky` per flow, plus
the defects with the screenshot that shows each. A flow on the repo skill's
known-failures list that fails as listed is `not verified (known: <ticket>)`,
not `fail`.

## 6. Clean up

Unless the user asked to keep it: the verifier runs the repo skill's stop
step, then `$SM forget` both helpers (session-manager, "Stopping on t3"), and
`git worktree remove --force <worktree>`. The evidence folder stays.

## 7. Report

Write `~/.agent-sessions/<feature>/verify-<n>.md`, verdict first:

| Verdict | When |
|---|---|
| **Verified** | every planned flow passed on its surface |
| **Partly verified** | at least one flow passed; the rest are not verified, none failed or flaky |
| **Not verified** | no flow could be driven |
| **Not working** | any flow failed or was flaky |

With no repo verify skill, the line ends `(weak evidence)`.

```
Partly verified (a1b2c3d): 3 of 4 flows pass; Windows install not verified (no Windows machine).

| Flow | Surface | Env | Result | Evidence |
|---|---|---|---|---|
| Admin blocks a skill | console | local | pass | blocks-skill/after.png |
Defects: 1 (the Cancel button leaves the dialog open: cancel/after.png)
Not verified: Windows install: no guest driver
```

Record it for pr-monitor in the PR's state file, named as pr-monitor names it
(`$PR_MONITOR_DIR`, default `~/.pr-monitor/`): `<project id>-<iid>.json` on
GitLab, as `mr-snapshot.sh` does, or `<repo>-<n>.json` on GitHub. Merge
`verify: {verified_sha, verdict, file}` into it, starting from `{}` when the
file doesn't exist, through a temp file and `mv`. Show the user the report. Posting it (in the PR
description's verification section, the repo's description skill decides
where, or as a comment) needs their yes.

## 8. Lock it in

For each flow verified by hand that the repo's suite doesn't cover, offer to
add it as a repeatable case in the form the repo skill names, so the next PR
that touches it is checked without an agent. Offer once, in one line; writing
the case is a change to the repo, made on the user's yes.

## When the output misses

A bug the verification passed and a user then hit is a gap in the repo's
verify skill: name the missing checklist item (trigger, check, the incident
behind it) and offer it as an edit to that skill. If the user is unhappy with
what this skill produced, load the `skill-improve` skill.
