---
name: ticket-manager
description: >-
  Link merge requests / pull requests to tickets and keep the ticket's status in
  step with the MR, through one `tm` command with a Python interface and
  pluggable trackers (Kaneo today): find or create the ticket when work starts
  or an MR is raised, move it to in-progress while the MR is open or Draft, to
  in-review when it is ready, to done when it merges to main, and comment when
  it is closed unmerged. Called when work on a change starts, by pr-raise and by
  pr-monitor; use directly when the user says "link this MR to a ticket",
  "update the ticket for MR 881", "what ticket is this PR for", "kaneo", names a
  ticket ID like ACME-154, or "ticket-manager".
---

# Ticket manager

You own the MR ↔ ticket link and the ticket's status. Every tracker call is one
command, `tm`, which prints JSON and exits non-zero with `{"error": …}` on
failure. The status rules (which column, when to leave a ticket alone, when to
comment) live in code, `ticket_manager/lifecycle.py`; don't re-derive them.

```bash
TM=~/codebase/ai-skills/ticket-manager/tm
```

**Backend:** chosen in `~/.config/ticket-manager/config.toml` (`backend =
"kaneo"`, the default, with `base_url`, `workspace_id` and `workspace_slug` under
`[kaneo]`). Interface:
`ticket_manager/interface.py`; Kaneo: `ticket_manager/backends/kaneo.py`.
Switching tracker means one more file in `backends/` and that config line.

**Credentials:** `KANEO_API_KEY`, else the macOS keychain entry `kaneo-api-key`,
else a hidden prompt on first use that caches it there. Off macOS, set
`KANEO_API_KEY`. `$TM reset-key` forgets it. Kaneo allows 100 requests per 60 s per key; one sync is about 4.

A ticket from another tracker (a GitHub or Jira URL): link it in the MR, skip
status sync, and say sync isn't supported for it.

## Ground rules

- Status moves and comments are **automatic** and always reported; no yes needed.
- **Creating** a ticket needs the user's yes.
- **Always give the ticket's full link** (`url` from `tm`), never its key or
  title alone: when confirming, offering matches, creating, reporting, and in
  the MR description. A key can't be clicked, and it isn't unique across trackers.
- `tm` enforces the guards: never out of done, never from a column a person set
  (`design-in-progress`, `in-staging-preview`, …), no move when already there,
  one comment per MR state. Report its `why` as given.

## Commands

| Need | Command |
|---|---|
| Resolve an ID | `$TM get ACME-154` → `{id, key, title, description, status, project_id, url}` |
| Search | `$TM search "csv export timeout" --limit 3` |
| Projects to create in | `$TM projects` |
| A project's columns | `$TM columns <project_id>` |
| Create (after a yes) | `$TM create --project <id> --title "…" --description-file <file>` (`-` reads stdin) |
| Every ticket in a project | `$TM list <project_id> [--status <slug>]` (all pages) |
| A ticket's history | `$TM history <KEY>`: comments and activity, oldest first |
| A ticket's links | `$TM relations <KEY>` |
| Comment | `$TM comment <KEY> "<markdown>"` |
| Move outside an MR | `$TM move <KEY> <slug>` (same guards; `done` means the final column) |
| Tracker reachable, key valid | `$TM health` |
| Work started | `$TM start <KEY> --branch <branch>` |
| Sync with the MR | `$TM sync <KEY> --relation fixes\|refs --mr-state open\|merged\|closed [--draft] [--valid-issues] [--merged-into <branch>] --mr-ref '!881' --mr-url <url> [--sha <sha>] [--reasons-file <file>] --state-file ~/.pr-monitor/<project>-<iid>.json` |

`start` and `sync` print `{ticket, url, from, to, commented, why}`.

## 0. Start (when work on a change begins)

Before the first edit of a task that will end in an MR, ask once for the ticket:
its link or ID, find or create one, or none. With a ticket, run **Link**, then
`$TM start <KEY> --branch <branch>`, remember the key for the session, and put it
in any new branch's name, so `pr-raise` finds it. "None" is final for the session:
don't ask again until `pr-raise`, which asks once more.

## 1. Link (at Start, or by pr-raise before the MR exists)

1. **The user gave an ID or URL:** `$TM get` it; show title, status and link so
   the user can confirm it's the right one.
2. **None given:** `$TM search` with keywords from the branch name, the commit
   subjects and the changed module. Offer up to 3 matches, each with its link,
   plus "create a new one" and "no ticket".
3. **Create (on a yes):** ask which project (offer the one matching the module, from
   `[module_projects]` in the config; ids from `$TM projects`), title from the MR title, description from the MR's Why
   section.

Return the key, the link and whether the MR **fixes** it or only **refs** it
(ask when unclear: one ticket split over several MRs is `Refs`). pr-raise writes
the first description line from it: `Fixes <KEY>: <url>` or `Refs <KEY>: <url>`

## 2. Sync (by pr-monitor on every run)

Find the key from the MR description's first `Fixes <KEY>` / `Refs <KEY>`, or
the `tickets` map in pr-monitor's state file. No ticket: nothing to do. Several
`Fixes`: sync each.

Run `$TM sync` with the MR's current state. What it does, so you can explain it:

| MR state | Moves to | Comment |
|---|---|---|
| open, Draft or with a valid issue | `in-progress` | "!881 open (Draft): <url>" plus the reasons |
| open, ready | `in-review` | "!881 ready for review: <url>" |
| merged into main, `fixes` | done (the final column) | "Merged to main in !881 (<sha>): <url>" |
| merged into main, `refs` | no move | same merge comment |
| merged into another branch | no move | "Merged into <branch> in !881" |
| closed unmerged | no move | "!881 closed without merging: <url>" |

It moves first, then comments, and records `tickets.<KEY>` in the state file,
so a state already commented on is not commented again.

## 3. Report

One line per ticket, inside the caller's report, from `tm`'s output:

```
Ticket https://kaneo.example/acme/task/ACME-154: in-progress → in-review (commented)
Ticket https://kaneo.example/acme/task/ACME-12: left in in-staging-preview (set by a person)
Ticket ACME-7: Kaneo unavailable, not synced
```

## Failure modes

- **Tracker unavailable, or `401`/`429`:** report `tm`'s error and go on. Never
  block the MR or the monitor on the tracker; the next sync retries.
- **The ID doesn't resolve:** report it once per MR; don't guess another ticket.
- **A rule looks wrong** (a move that shouldn't happen): fix it in
  `lifecycle.py` with a test in `tests/`, not by working around it here.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
