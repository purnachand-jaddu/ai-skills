#!/bin/zsh
# stale-watches.sh [--sync] [--restart] | --mark <project>-<iid>: lists watched GitLab MRs that merged or closed and aren't closed out, and open watched ones (watched_by) unchecked for LOOP_STALE_SECONDS; --sync syncs tickets; --restart resends the tick to a stale monitor on t3; --mark closes one out.
set -euo pipefail
STATE_DIR=${PR_MONITOR_DIR:-$HOME/.pr-monitor}
STALE_SECONDS=${STALE_SECONDS:-0}
LOOP_STALE_SECONDS=${LOOP_STALE_SECONDS:-1800}
TM=${TM:-$HOME/codebase/ai-skills/ticket-manager/tm}
T3=${T3:-$HOME/.t3/bin/t3}

if [[ ${1:-} == --mark ]]; then
  f="$STATE_DIR/$2.json"
  jq --arg at "$(date -u +%FT%TZ)" '.closed_out = $at' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  exit 0
fi
sync=; restart=
for a in "$@"; do [[ $a == --sync ]] && sync=1; [[ $a == --restart ]] && restart=1; done

now=$(date -u +%s)
to_epoch() { date -j -u -f %FT%TZ "$1" +%s 2>/dev/null || date -u -d "$1" +%s; }

# Resends the /loop tick to the monitor thread in watched_by, at most once per LOOP_STALE_SECONDS.
restart_loop() {
  local f=$1 thread caller url last
  thread=$(jq -r '.watched_by.thread? // empty' "$f"); caller=$(jq -r '.watched_by.caller? // empty' "$f"); url=$(jq -r '.watched_by.url? // empty' "$f")
  [[ -z $thread || -z $caller || -z $url ]] && { jq -nc --arg w "${f:t:r}" '{watch: $w, restart: "skipped: watched_by has no thread, caller or url"}'; return; }
  last=$(jq -r '.restarted_at // empty' "$f")
  [[ -n $last ]] && (( now - $(to_epoch "$last") < LOOP_STALE_SECONDS )) && return
  local result=sent
  "$T3" thread send "$thread" "/loop pr-monitor $url — monitor tick: you are the monitor helper; run a check now, then schedule the next; report events to $caller" >/dev/null 2>&1 || result=failed
  # Stamped on failure too, so a gone thread is retried once per LOOP_STALE_SECONDS, not every run.
  jq --arg at "$(date -u +%FT%TZ)" '.restarted_at = $at' "$f" > "$f.restart.tmp" && mv "$f.restart.tmp" "$f"
  jq -nc --arg w "${f:t:r}" --arg t "$thread" --arg r "$result" '{watch: $w, restart: $r, thread: $t}'
}
for f in "$STATE_DIR"/<->-<->.json(N); do
  # Skip closed-out watches and, when STALE_SECONDS is set, anything checked within it.
  jq -e '.closed_out' "$f" >/dev/null && continue
  checked=$(jq -r '.checked_at // empty' "$f")
  age=0; [[ -n $checked ]] && age=$(( now - $(to_epoch "$checked") ))
  [[ -n $checked ]] && (( STALE_SECONDS > 0 )) && (( age < STALE_SECONDS )) && continue
  loop_stale=false; (( age > LOOP_STALE_SECONDS )) && jq -e '.watched_by' "$f" >/dev/null && loop_stale=true

  name=${f:t:r}; pid=${name%-*}; iid=${name#*-}
  mr=$(glab api "projects/$pid/merge_requests/$iid" 2>/dev/null) || { jq -nc --arg w "$name" '{watch: $w, error: "MR not readable"}'; continue; }
  line=$(jq -c --arg w "$name" --slurpfile s "$f" --argjson loop_stale $loop_stale '
    if .state == "opened" then (select($loop_stale) | {watch: $w, iid, url: .web_url, state, loop: "stale", last_checked: $s[0].checked_at}) else
    select(.state == "merged" or .state == "closed") | {
      watch: $w, iid, url: .web_url, state, merged_into: .target_branch, sha: (.merge_commit_sha // .squash_commit_sha // .sha), head_sha: .sha,
      merged_at, closed_at, last_checked: $s[0].checked_at,
      tickets: ([($s[0].tickets // {}) | to_entries[] | {key, relation: .value.relation, last: .value.last_mr_state}] + [$s[0].ticket // empty | {key: .id, relation, last: .last_mr_state}] | unique_by(.key))
    } end' <<<"$mr")
  [[ -z $line ]] && continue
  print -r -- "$line"
  # A dead loop is woken after a merge until its final event is recorded, so it still sends it.
  needs_tick=true; [[ $(jq -r .state <<<"$line") != opened ]] && jq -e '.final_event_at' "$f" >/dev/null && needs_tick=false
  [[ -n $restart ]] && $loop_stale && $needs_tick && restart_loop "$f"
  [[ -z $sync || $(jq -r .state <<<"$line") == opened ]] && continue

  # Sync each ticket not already synced to the final state; tm comments once per state.
  jq -c '. as $m | .tickets[] | select((.last // "") | test("^(merged|closed)") | not) | {key, relation, m: $m}' <<<"$line" | while read -r t; do
    key=$(jq -r .key <<<"$t"); rel=$(jq -r '.relation // "fixes"' <<<"$t")
    state=$(jq -r .m.state <<<"$t"); into=$(jq -r .m.merged_into <<<"$t"); url=$(jq -r .m.url <<<"$t"); sha=$(jq -r .m.sha <<<"$t")
    args=(sync "$key" --relation "$rel" --mr-state "$state" --mr-ref "!$iid" --mr-url "$url" --sha "$sha" --state-file "$f")
    [[ $state == merged ]] && args+=(--merged-into "$into")
    "$TM" "${args[@]}" | jq -c '{ticket, from, to}' || jq -nc --arg k "$key" '{ticket: $k, error: "sync failed"}'
  done
done
