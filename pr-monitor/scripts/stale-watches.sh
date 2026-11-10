#!/bin/zsh
# stale-watches.sh [--sync | --mark <project>-<iid>]: lists watched GitLab MRs that merged or closed and aren't closed out; --sync also syncs their tickets; --mark closes one out.
set -euo pipefail
STATE_DIR=${PR_MONITOR_DIR:-$HOME/.pr-monitor}
STALE_SECONDS=${STALE_SECONDS:-0}
TM=${TM:-$HOME/codebase/ai-skills/ticket-manager/tm}

if [[ ${1:-} == --mark ]]; then
  f="$STATE_DIR/$2.json"
  jq --arg at "$(date -u +%FT%TZ)" '.closed_out = $at' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  exit 0
fi
sync=; [[ ${1:-} == --sync ]] && sync=1

now=$(date -u +%s)
for f in "$STATE_DIR"/<->-<->.json(N); do
  # Skip closed-out watches and, when STALE_SECONDS is set, anything checked within it.
  jq -e '.closed_out' "$f" >/dev/null && continue
  checked=$(jq -r '.checked_at // empty' "$f")
  [[ -n $checked ]] && (( STALE_SECONDS > 0 )) && (( now - $(date -j -u -f %FT%TZ "$checked" +%s 2>/dev/null || date -u -d "$checked" +%s) < STALE_SECONDS )) && continue

  name=${f:t:r}; pid=${name%-*}; iid=${name#*-}
  mr=$(glab api "projects/$pid/merge_requests/$iid" 2>/dev/null) || { jq -nc --arg w "$name" '{watch: $w, error: "MR not readable"}'; continue; }
  line=$(jq -c --arg w "$name" --slurpfile s "$f" 'select(.state == "merged" or .state == "closed") | {
      watch: $w, iid, url: .web_url, state, merged_into: .target_branch, sha: (.merge_commit_sha // .squash_commit_sha // .sha),
      merged_at, closed_at, last_checked: $s[0].checked_at,
      tickets: ([($s[0].tickets // {}) | to_entries[] | {key, relation: .value.relation, last: .value.last_mr_state}] + [$s[0].ticket // empty | {key: .id, relation, last: .last_mr_state}] | unique_by(.key))
    }' <<<"$mr")
  [[ -z $line ]] && continue
  print -r -- "$line"
  [[ -z $sync ]] && continue

  # Sync each ticket not already synced to the final state; tm comments once per state.
  jq -c '. as $m | .tickets[] | select((.last // "") | test("^(merged|closed)") | not) | {key, relation, m: $m}' <<<"$line" | while read -r t; do
    key=$(jq -r .key <<<"$t"); rel=$(jq -r '.relation // "fixes"' <<<"$t")
    state=$(jq -r .m.state <<<"$t"); into=$(jq -r .m.merged_into <<<"$t"); url=$(jq -r .m.url <<<"$t"); sha=$(jq -r .m.sha <<<"$t")
    args=(sync "$key" --relation "$rel" --mr-state "$state" --mr-ref "!$iid" --mr-url "$url" --sha "$sha" --state-file "$f")
    [[ $state == merged ]] && args+=(--merged-into "$into")
    "$TM" "${args[@]}" | jq -c '{ticket, from, to}' || jq -nc --arg k "$key" '{ticket: $k, error: "sync failed"}'
  done
done
