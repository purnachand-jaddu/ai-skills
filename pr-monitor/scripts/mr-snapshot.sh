#!/bin/zsh
# mr-snapshot.sh [mr-number-or-url]: prints one JSON digest of a GitLab MR (review threads, pipeline, failed jobs, tests, coverage, conflicts) and what changed since the last run.
set -euo pipefail
STATE_DIR=${PR_MONITOR_DIR:-$HOME/.pr-monitor}
mkdir -p "$STATE_DIR"

# The MR: an explicit number or URL, else the one for the current branch.
mr=$(glab mr view ${1:-} -F json 2>/dev/null) || { echo '{"error":"no merge request found; pass a number or URL"}'; exit 1; }
pid=$(jq -r .project_id <<<"$mr"); iid=$(jq -r .iid <<<"$mr"); target=$(jq -r .target_branch <<<"$mr")
api() { glab api "$1" 2>/dev/null || echo 'null'; }

# Review threads: unresolved resolvable ones, and every human note with its id so new ones can be told apart.
discussions=$(api "projects/$pid/merge_requests/$iid/discussions?per_page=100")
threads=$(jq '[.[]? | select(.notes[0].system | not) | {id, resolvable: .notes[0].resolvable, resolved: (.notes | all(.resolved // false)), path: .notes[0].position.new_path, line: .notes[0].position.new_line, notes: [.notes[] | {id, author: .author.username, created_at, body: (.body | .[0:600])}]}]' <<<"$discussions")

# Head pipeline, its failed jobs and test summary.
pipeline=$(jq '.head_pipeline // .pipeline // {}' <<<"$mr")
pipe_id=$(jq -r '.id // empty' <<<"$pipeline")
jobs='[]'; tests='null'
if [[ -n $pipe_id ]]; then
  jobs=$(api "projects/$pid/pipelines/$pipe_id/jobs?per_page=100&include_retried=false" | jq '[.[]? | {id, name, stage, status, allow_failure, web_url, coverage}]')
  tests=$(api "projects/$pid/pipelines/$pipe_id/test_report_summary" | jq '.total? // null')
fi

# Coverage on the target branch's last successful pipeline, the baseline a drop is measured against.
base_cov=$(api "projects/$pid/pipelines?ref=$target&status=success&per_page=1" | jq -r '.[0].coverage // empty')

# What changed since the previous snapshot of this MR.
state="$STATE_DIR/$pid-$iid.json"
prev=$( [[ -f $state ]] && cat "$state" || echo '{}' )
last_note=$(jq -r '.last_note_id // 0' <<<"$prev")
snapshot=$(jq -n --argjson mr "$mr" --argjson threads "$threads" --argjson pipeline "$pipeline" --argjson jobs "$jobs" --argjson tests "$tests" \
  --arg base_cov "$base_cov" --argjson prev "$prev" --argjson last_note "$last_note" '
  {
    mr: {iid: $mr.iid, project_id: $mr.project_id, title: $mr.title, url: $mr.web_url, state: $mr.state, draft: ($mr.draft // $mr.work_in_progress // false),
         sha: $mr.sha, source_branch: $mr.source_branch, target_branch: $mr.target_branch,
         merge_status: ($mr.detailed_merge_status // $mr.merge_status), has_conflicts: ($mr.has_conflicts // false)},
    threads: {unresolved: [$threads[] | select(.resolvable and (.resolved | not))], new_notes: [$threads[] | .notes[] | select(.id > $last_note)]},
    pipeline: {id: $pipeline.id, status: $pipeline.status, sha: $pipeline.sha, url: $pipeline.web_url, coverage: ($pipeline.coverage | if . == "" then null else . end), target_coverage: ($base_cov | if . == "" then null else . end),
               failed_jobs: [$jobs[] | select(.status == "failed")], running_jobs: [$jobs[] | select(.status == "running" or .status == "pending") | .name],
               tests: $tests},
    changed_since_last: {
      first_run: ($prev == {}),
      sha: ($prev.sha != $mr.sha),
      pipeline: (($prev.pipeline_id // null) != $pipeline.id or ($prev.pipeline_status // null) != $pipeline.status),
      new_note_count: ([$threads[] | .notes[] | select(.id > $last_note)] | length)
    }
  }')
jq -n --argjson s "$snapshot" --argjson threads "$threads" '{sha: $s.mr.sha, pipeline_id: $s.pipeline.id, pipeline_status: $s.pipeline.status,
  last_note_id: ([$threads[] | .notes[] | .id] | max // 0), draft_reason: null, checked_at: (now | todate)}' > "$state.tmp"
# Keep fields the skill writes (draft_reason, review, ticket) across runs; fresh snapshot fields win.
jq -s '.[1] + .[0] + {draft_reason: (.[1].draft_reason // null)}' "$state.tmp" <(echo "$prev") > "$state" && rm -f "$state.tmp"
echo "$snapshot"
