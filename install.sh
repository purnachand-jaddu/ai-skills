#!/usr/bin/env bash
# Symlink every skill into ~/.claude/skills, link CODING_STANDARD.md for Claude and Codex, seed the ticket-manager and machines configs, then run setup/install.sh.
# Safe to re-run. Never overwrites a real (non-symlink) directory or an existing config.
set -euo pipefail
AI="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mkdir -p "$SKILLS_DIR"

# remove links to skills that were renamed or deleted in this repo
for link in "$SKILLS_DIR"/*; do
  if [ -L "$link" ] && [[ "$(readlink "$link")" == "$AI"/* ]] && [ ! -e "$link" ]; then
    rm "$link"; echo "removed stale link $link"
  fi
done

for dir in "$AI"/*/; do
  [ -f "$dir/SKILL.md" ] || continue
  name="$(basename "$dir")"; link="$SKILLS_DIR/$name"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    echo "skip $name: $link exists and is not a symlink" >&2; continue
  fi
  ln -sfn "${dir%/}" "$link"; echo "linked $link -> ${dir%/}"
done

TM_CONFIG="$HOME/.config/ticket-manager/config.toml"
if [ ! -f "$TM_CONFIG" ]; then
  mkdir -p "$(dirname "$TM_CONFIG")"
  cp "$AI/config/ticket-manager.toml.example" "$TM_CONFIG"
  echo "created $TM_CONFIG — set base_url, workspace_id and workspace_slug"
fi

M_CONFIG="$HOME/.config/machines/config.toml"
if [ ! -f "$M_CONFIG" ]; then
  mkdir -p "$(dirname "$M_CONFIG")"
  cp "$AI/config/machines.toml.example" "$M_CONFIG"
  echo "created $M_CONFIG — list your machines"
fi

# Links CODING_STANDARD.md into an agent's config dir and adds its reference line to that agent's instructions file once.
link_standard() {
  local dir=$1 file=$2 line=$3 link="$1/CODING_STANDARD.md"
  [ -d "$dir" ] || return 0
  if [ -e "$link" ] && [ ! -L "$link" ]; then echo "skip $link: exists and is not a symlink" >&2; return 0; fi
  ln -sfn "$AI/CODING_STANDARD.md" "$link"
  touch "$dir/$file"
  grep -qxF "$line" "$dir/$file" || { printf '\n%s\n' "$line" >> "$dir/$file"; echo "added the coding standard to $dir/$file"; }
}
link_standard "$HOME/.claude" CLAUDE.md "@CODING_STANDARD.md"
link_standard "$HOME/.codex" AGENTS.md "Follow the coding standard in ~/.codex/CODING_STANDARD.md; read it before you write code."

# third-party plugins, skills and tools (setup/third-party.json)
"$AI/setup/install.sh"
