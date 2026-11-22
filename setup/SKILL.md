---
name: setup
description: >-
  Set up this machine for the user's skills: link the ai-skills repo's own
  skills, and install the third-party plugins, skills and CLI tools listed in
  setup/third-party.json, through setup/install.sh. Also adds a new third-party
  skill or plugin to that list (find its source, pin a commit, install it), and
  finds installed skills nobody recorded. Use when the user says "set up my
  skills", "install my third-party skills", "new machine", "add this skill to my
  setup", "add <skill URL> to the list", "what skills aren't tracked", or
  "setup". Never accepts a plugin's install command on the user's behalf.
---

# Setup

The list is `setup/third-party.json` in the ai-skills repo; `setup/install.sh`
applies it. The script does the installing; you run it, read its report and
change the list. The repo is wherever this skill really lives: `AI=$(dirname
"$(readlink -f <this skill's base directory>)")`, since the base directory is
usually a link in `~/.claude/skills`.

## Ground rules

- **The list is the source of truth.** Install a third-party skill by adding it
  to the list and running the script, never by copying a folder into
  `~/.claude/skills`.
- **Pin, don't vendor.** A git skill is a repo, a path to the folder holding
  `SKILL.md`, and a full commit sha; the clone lives in
  `~/.cache/ai-skills/third-party/<name>`, never in this repo.
- **Third-party code is read before it is listed.** Read the skill's `SKILL.md`
  and any scripts it ships; say what it runs, needs, and sends anywhere.
- **Tools are reported, not installed.** The script prints the install line for
  a missing CLI; run it only on the user's yes.
- **A plugin that installs by running a command** asks for confirmation, which
  your shell (no TTY) can't give: run `claude plugin install <id> --json`, show
  the user its `shownCommand`, and only on their yes re-run with
  `--accept-command <shownCommand.sha256>`. Or ask them to run it in their
  terminal. Never pass `-y`.
- Changing the list ends in an MR: `pr-raise`.

## Set up a machine

```bash
"$AI/install.sh"                # links this repo's skills, CODING_STANDARD.md and RESEARCH.md, then runs setup/install.sh
"$AI/setup/install.sh" --check  # report only
```

On a new machine nothing is linked yet: clone the repo anywhere and run its
`install.sh`. Run it from that main checkout, not a worktree, since the links
it makes point at the checkout it runs from.

Each line is `ok`, `added`, `removed`, `optional` (a tool only some skills
need), `untracked`, `missing`, `skipped`, `failed` or `stale` (a link to a
skill no longer listed; `--check` only); exit 1 on any of the last four. Report the non-`ok` lines
and what each needs: a tool to install, a sign-in (`glab auth login`,
`gh auth login`), a plugin command to confirm, or a real folder in the way
(`skipped`: it was copied in by hand; offer to list it and replace it).

## Add a skill or plugin

1. **Find the source** from what the user gave (docs page, repo, plugin name).
   Prefer, in order: a plugin in a marketplace (`claude plugin marketplace
   add <owner/repo>`, `claude plugin install <name>@<marketplace>`), then a git
   repo. A skills installer such as `npx skills add <repo>` means a git repo:
   take the repo and the folder holding `SKILL.md`.
2. **Pin it:** `git ls-remote <repo> HEAD` for the sha; check the license
   (`gh api repos/<owner>/<repo> -q .license.spdx_id`) and that `<path>/SKILL.md`
   exists.
3. **Read it** (ground rules) and summarise in two or three lines.
4. **Add the entry** to `third-party.json` (`skills`: name, repo, path (`.`
   for the repo root), ref, docs; `plugins`: `name@marketplace`, plus the
   marketplace if new), run `setup/install.sh`, and check the skill now shows
   in the skills list.
5. **Update** an entry by moving `ref` to a newer sha after reading the diff
   (`git -C ~/.cache/ai-skills/third-party/<name> log --oneline <old>..<new>`).

## Remove a skill

Delete its entry and run `setup/install.sh`: it removes the link (`removed`)
and keeps the clone in the cache. For a plugin, also `claude plugin uninstall
<name@marketplace>`; the script doesn't uninstall plugins.

## Untracked skills

`untracked` lines are skill folders that are neither this repo's, nor listed,
nor plugin-managed. For each: find its source (search the name and a line of
its `SKILL.md`), and offer one of: add it to the list, move it into this repo
if it is the user's own, or leave it. Don't delete one without a yes.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
