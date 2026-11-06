---
name: fleet-setup
description: Install, configure, check, and move the agent fleet onto a machine — dependencies (tmux, ttyd, glab, cloudflared, Claude Code), skill links, ticket tracker config, project→repo mapping, the dispatch schedule, dashboard/tunnel services, and a bundle to copy the setup to another VM. Use when setting up a new VM, diagnosing why the fleet isn't working ("fleet doctor"), or transferring the fleet to another machine.
---

# Fleet setup

One script: `~/codebase/ai-skills/fleet-setup/scripts/setup.sh <command>`. Every command is
idempotent. **Start with `doctor`** — it checks everything and prints the exact fix for
each problem; work down its list.

| Command | Does |
|---|---|
| `doctor` | Tools, logins, skill links, config, ticket backend reachability, project repos (git identity + origin), schedule, services |
| `deps [--with-claude]` | apt: git, python3, curl, tmux, ttyd, glab · cloudflared .deb · disables Ubuntu's stock ttyd login service · `--with-claude` runs Claude Code's native installer if missing |
| `install` | Runs `~/codebase/ai-skills/install.sh`: symlinks skills into `~/.claude/skills`, `fleet` into `~/.local/bin`, seeds `~/.agent-fleet` |
| `config KEY=VALUE … [--gen-token]` | Edits `~/.agent-fleet/config.env` in place (stays chmod 600); `--gen-token` makes a `DASHBOARD_TOKEN` |
| `project add <tracker-project-id> <path\|git-url> [base]` | Maps a tracker project to a repo; clones URLs into `~/repos/`; base defaults to the remote's HEAD |
| `schedule on [min] \| off` | systemd timer running `fleet tick` (default every 5 min) |
| `services on [tunnel host] \| off` | systemd units for the dashboard and, if given, a named cloudflared tunnel |
| `bundle [file]` | Packs `~/codebase/ai-skills` (git history included) into one file for another VM |
| `all [--with-claude]` | `deps` → `install` → `doctor` |

## New VM, start to finish

```bash
# on the old machine
~/codebase/ai-skills/fleet-setup/scripts/setup.sh bundle /tmp/ai-skills.bundle
scp /tmp/ai-skills.bundle newvm:/tmp/
# (or push ~/codebase/ai-skills to a private git remote and clone that instead)

# on the new VM
git clone /tmp/ai-skills.bundle ~/codebase/ai-skills
S=~/codebase/ai-skills/fleet-setup/scripts/setup.sh
$S all --with-claude
claude            # /login once — interactive, the human does this
glab auth login   # interactive
git config --global user.name "…"; git config --global user.email "…"
$EDITOR ~/.config/ticket-manager/config.toml   # base_url, workspace_id, workspace_slug
$S config KANEO_API_KEY=kan_live_… FLEET_NODE=vm2 --gen-token
$S project add <tracker-project-id> https://gitlab.com/group/repo.git
$S doctor
$S schedule on
$S services on                           # dashboard only; add `fleet fleet-vm2.example.com` for a tunnel
```

Logins (`claude`, `glab auth login`, `cloudflared tunnel login`) are interactive: ask the
user to run them (in Claude Code: `! glab auth login`). Never paste tokens into chat.

## Several VMs, one tracker
- Point every VM at the **same** tracker (e.g. one Kaneo); don't run a tracker per VM.
- Give each a distinct `FLEET_NODE` (defaults to hostname). It appears on ticket comments
  and every event, so you can tell which machine did what.
- The launcher re-reads a ticket's status right before claiming it and claims it before any
  slow git work, so two VMs rarely grab the same ticket. To rule it out entirely, split the
  work: map different tracker projects per VM, or give each VM its own `FLEET_PICK_LABEL`
  (e.g. `agent-vm2`) and label tickets accordingly.
- Each VM runs its own dashboard (its own runs). Give each tunnel its own hostname.

## What is per machine (not in the bundle)
`~/.agent-fleet/` — `config.env` (tracker credentials, dashboard token), `projects.json` (local repo
paths), runs, worktrees. Logins live in `~/.claude`, `~/.config/glab-cli`, `~/.cloudflared`.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
