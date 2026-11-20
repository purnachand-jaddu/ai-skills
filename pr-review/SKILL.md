---
name: pr-review
description: >-
  Review a pull request / merge request by handing it to the diff-review skill:
  the PR/MR number, URL or branch becomes diff-review's target, and diff-review
  does all the work and reporting. Use when the user says "pr-review", "review
  PR 12", "review MR 858", "review this PR" or pastes a PR/MR link to review.
  Also posts the verified findings as line comments on the MR/PR when the user
  asks for that ("review MR 941 and comment", "post the findings on the PR",
  "--comment"). Read-only otherwise, like diff-review.
---

# PR review

Load the `diff-review` skill and run it with the PR/MR as its target (number,
URL or branch, as given). Follow it as written; this skill adds nothing to it.

No PR/MR given: let `diff-review` find the one for the current branch.

## Comments on the MR/PR

Only when the user asked for comments, in this request or for a report already
in hand. diff-review stays read-only; the posting happens here, after its report.

1. **What gets posted:** every finding that survived diff-review's verification
   (its "When the report arrives" step), whatever its severity, one comment each.
   Dropped findings and the "Not counted" line are never posted.
2. **Write them** to a scratchpad JSON list, one object per finding:
   `severity`, `title`, `path` and `line` (the line it cites), and `body`, the
   report's detail plus its `Scenario:` and `Suggest:` lines, as written.
3. **Post** with `~/.claude/skills/pr-review/scripts/post-findings.py <mr-or-pr-url>
   <json> --verdict "<the report's first line>" --reviewed <sha the review read>
   --model <model> --provider <provider> --harness <harness>`. Run it with `--dry-run` first and check the plan.
   The three names are yours, as you run now: for example `Claude Opus 5.5` /
   `Anthropic` / `Claude Code`, or a GPT model / `OpenAI` / `Codex`. Never
   copy them from an example or an earlier comment.
4. **Report** each line it printed: `line` (on that path:line), `general`,
   `skipped` (already posted) or `failed` (with the error).

What the script does, so you don't do it by hand:
- **Header.** Each comment opens with `**Agent review** — <model> (<provider>),
  via <harness> · diff-review, verified at <sha>`, then the bold severity and title.
- **Summary note first.** A general note opens with the verdict label in bold
  (**Do not merge**, **Merge after fixes** or **Mergeable**), then its sentence and
  one line per finding. A verdict without one of the three labels is refused.
- **Anchoring.** It re-reads the MR's current `diff_refs`, so a head that moved
  since the review is caught. A finding goes on its line only when that line is
  an added line at the current head and its text is unchanged since `--reviewed`,
  or appears exactly once there. Otherwise it becomes a general comment that
  names `path:line`.
- **GitLab request body.** It posts JSON (`--input`), because `glab api -F
  "position[new_line]=..."` doesn't nest and GitLab then silently files a general
  comment. It checks that the reply's `position.new_path` is set. On GitHub it
  posts `pulls/<n>/comments` with `commit_id`, `path`, `line` and `side`.
- **No duplicates.** Each comment carries a hidden marker per path and title, so a
  re-run skips findings already posted.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
