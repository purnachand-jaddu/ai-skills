#!/usr/bin/env bash
# Installs the third-party plugins, skills and tools listed in third-party.json; --check only reports.
# Safe to re-run. Never overwrites a real (non-symlink) skill directory; never auto-accepts a plugin's install command.
set -euo pipefail
SETUP="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
AI="$(dirname "$SETUP")"
LIST="${THIRD_PARTY_LIST:-$SETUP/third-party.json}"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
CACHE="${THIRD_PARTY_CACHE:-$HOME/.cache/ai-skills/third-party}"
check=; [[ ${1:-} == --check ]] && check=1
fail=0
shopt -s nullglob
US=$'\x1f'  # field separator for jq rows; not whitespace, so empty fields survive read

say() { printf '%-10s %s\n' "$1" "$2"; }
command -v jq >/dev/null || { say missing "tool jq (reads the list): brew install jq"; exit 1; }

# Tools: report missing ones with their install command; installing them is left to the user. Optional ones don't fail the run.
while IFS=$US read -r name install for optional; do
  if command -v "$name" >/dev/null; then say ok "tool $name"
  elif [[ $optional == true ]]; then say optional "tool $name ($for): $install"
  else say missing "tool $name ($for): $install"; fail=1; fi
done < <(jq -r '.tools[] | [.name, .install, (.for // ""), (.optional // false | tostring)] | join("\u001f")' "$LIST")

# A failing listing skips only the plugin section, so the skills below still run.
if ! command -v claude >/dev/null; then
  say missing "claude CLI: plugins and marketplaces not checked"; fail=1
elif ! have_mp=$(claude plugin marketplace list --json | jq -r '.[].name') || ! have_pl=$(claude plugin list --json | jq -r '.[].id'); then
  say failed "claude plugin list --json: plugins and marketplaces not checked"; fail=1
else
  while IFS=$US read -r name repo; do
    if grep -qx "$name" <<<"$have_mp"; then say ok "marketplace $name"
    elif [[ -n $check ]]; then say missing "marketplace $name ($repo)"; fail=1
    else claude plugin marketplace add "$repo" >/dev/null && say added "marketplace $name" || { say failed "marketplace $name ($repo)"; fail=1; }
    fi
  done < <(jq -r '.marketplaces[] | [.name, .repo] | join("\u001f")' "$LIST")

  while read -r id; do
    if grep -qx "$id" <<<"$have_pl"; then say ok "plugin $id"
    elif [[ -n $check ]]; then say missing "plugin $id"; fail=1
    elif out=$(claude plugin install "$id" 2>&1 </dev/null); then say added "plugin $id"
    else say failed "plugin $id (run: claude plugin install $id)"; sed 's/^/           /' <<<"$out"; fail=1
    fi
  done < <(jq -r '.plugins[]' "$LIST")
fi

# Git skills: a clone per skill at its pinned ref, linked into the skills dir.
while IFS=$US read -r name repo path ref; do
  clone="$CACHE/$name"; src="$clone/$path"; [[ $path == . ]] && src=$clone; link="$SKILLS_DIR/$name"
  if [[ -e $link && ! -L $link ]]; then say skipped "skill $name: $link exists and is not a symlink"; fail=1; continue; fi
  if [[ -L $link && "$(readlink "$link")" == "$src" && "$(git -C "$clone" rev-parse HEAD 2>/dev/null)" == "$ref" ]]; then say ok "skill $name"; continue; fi
  if [[ -n $check ]]; then say missing "skill $name ($repo@${ref:0:7})"; fail=1; continue; fi
  [[ -d $clone/.git ]] || git clone -q "$repo" "$clone" || { say failed "skill $name: cannot clone $repo"; fail=1; continue; }
  { git -C "$clone" remote set-url origin "$repo" || git -C "$clone" remote add origin "$repo"; } 2>/dev/null &&
    git -C "$clone" fetch -q origin "$ref" && git -C "$clone" checkout -q --detach "$ref" || true
  # Link only the pinned commit: a failed fetch leaves the clone on unread code.
  [[ "$(git -C "$clone" rev-parse HEAD)" == "$ref" ]] || { say failed "skill $name: cannot check out $ref"; fail=1; continue; }
  [[ -f $src/SKILL.md ]] || { say failed "skill $name: no SKILL.md at $path"; fail=1; continue; }
  mkdir -p "$SKILLS_DIR"; ln -sfn "$src" "$link"; say added "skill $name -> $repo@${ref:0:7}"
done < <(jq -r '.skills[] | [.name, .repo, (if (.path // "") == "" then "." else .path end), .ref] | join("\u001f")' "$LIST")

# Links into the cache whose skill is no longer listed.
listed=$(jq -r '.skills[].name' "$LIST")
for link in "$SKILLS_DIR"/*; do
  [[ -L $link && "$(readlink "$link")" == "$CACHE"/* ]] || continue
  name=$(basename "$link"); grep -qx "$name" <<<"$listed" && continue
  if [[ -n $check ]]; then say stale "skill $name (no longer listed)"; fail=1; else rm "$link"; say removed "skill $name (clone kept in $CACHE/$name)"; fi
done

# Skills that are neither this repo's, nor listed, nor plugin-managed: candidates for the list.
ai_remote=$(git -C "$AI" remote get-url origin 2>/dev/null || true)
for d in "$SKILLS_DIR"/*/; do
  name=$(basename "$d"); target=$(readlink "${d%/}" || true)
  [[ $target == "$AI"/* || $target == "$CACHE"/* ]] && continue
  # Links into another checkout of this repo (a worktree, a second clone) are this repo's too.
  [[ -n $target && -n $ai_remote && "$(git -C "$target" remote get-url origin 2>/dev/null)" == "$ai_remote" ]] && continue
  grep -qx "$name" <<<"$listed" && continue
  say untracked "skill $name (${target:-copied directory})"
done

exit $fail
