#!/usr/bin/env bash
# Symlink every skill into ~/.claude/skills and seed the ticket-manager config.
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
