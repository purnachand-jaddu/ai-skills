#!/bin/zsh
# stale-watches.sh [--mark <project>-<iid>]: lists watched GitLab MRs that merged or closed after their last check, or marks one as closed out.
set -euo pipefail
STATE_DIR=${PR_MONITOR_DIR:-$HOME/.pr-monitor}
STALE_SECONDS=${STALE_SECONDS:-3600}

if [[ ${1:-} == --mark ]]; then
  f="$STATE_DIR/$2.json"
  jq --arg at "$(date -u +%FT%TZ)" '.closed_out = $at' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  exit 0
fi

now=$(date -u +%s)
for f in "$STATE_DIR"/<->-<->.json(N); do
  # Skip closed-out watches, finished ticket syncs, and anything checked within the window.
  jq -e '.closed_out' "$f" >/dev/null && continue
  jq -e '[(.tickets // {})[], (.ticket // empty)] | map(.last_mr_state // "") | any(test("^(merged|closed)"))' "$f" >/dev/null && continue
  checked=$(jq -r '.checked_at // empty' "$f")
  [[ -n $checked ]] && (( now - $(date -j -u -f %FT%TZ "$checked" +%s 2>/dev/null || date -u -d "$checked" +%s) < STALE_SECONDS )) && continue

  name=${f:t:r}; pid=${name%-*}; iid=${name#*-}
  mr=$(glab api "projects/$pid/merge_requests/$iid" 2>/dev/null) || { jq -nc --arg w "$name" '{watch: $w, error: "MR not readable"}'; continue; }
  jq -c --arg w "$name" --slurpfile s "$f" 'select(.state == "merged" or .state == "closed") | {
      watch: $w, iid, url: .web_url, state, merged_into: .target_branch, sha: (.merge_commit_sha // .squash_commit_sha // .sha),
      merged_at, closed_at, last_checked: $s[0].checked_at,
      tickets: ([($s[0].tickets // {}) | to_entries[] | {key, relation: .value.relation}] + [$s[0].ticket // empty | {key: .id, relation}] | unique_by(.key))
    }' <<<"$mr"
done
