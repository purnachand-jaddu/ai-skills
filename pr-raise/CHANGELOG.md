2026-11-24: actions the user's instructions pre-authorise stand in for a yes: the ticket and reviewer asks are skipped, the step 4 plan is shown and the skill commits, pushes and opens the MR without waiting. 67 of 441 user messages across 70 T3 threads were bare yeses to asks like this
2026-11-24: a repo description skill (`pr-description` or `*-pr-description` under .agents/skills or .claude/skills on the target) sets the MR description layout in place of the default; radius added surface-pr-description (!1095) and pr-raise would have ignored it
2026-11-20: the pre-push review's verdict decides: Do not merge is a failed check (Draft), the other two put their findings in the plan. a !941 verdict read "mergeable once two parity gaps are fixed", so a reader could not tell whether to merge
2026-11-16: scripts are called through ~/.claude/skills/<skill>/ instead of ~/codebase/ai-skills/, so the skill works wherever the repo is cloned. The repo path only held on one machine
2026-11-13: a Draft raised for failing checks is undrafted by pr-monitor once its draft_reason is resolved, not by asking the user
2026-11-11: the create guard also catches bash/sh -c and wrappers with their arguments (env -u, sudo -u, timeout 60), and skips heredoc bodies written as data while still checking the heredoc's own line; a review found both gaps
2026-11-11: the only way to open an MR, one run per MR in a batch; step 5's creates carry PR_RAISE=1 and a PreToolUse hook (hooks/mr_create_guard.py) blocks any other `glab mr create` / `gh pr create`. A coordinator opened 8 MRs by hand and none got a pr-monitor
2026-11-11: runs one diff-review of the MR's changes before the plan and names its report in pr-monitor's first message; reviews start here, in pr-monitor and pr-takeover, or on request, not before every push. User saw three reviewer threads for one push
2026-11-11: removed the headless run for fleet workers; the agent fleet skills were removed
2026-11-06: always give the ticket's full link, not its key or title alone (asking, creating, reporting, MR description); user wanted the whole link
2026-11-06: shortened wording, no rule changed; user asked for fewer words
2026-11-06: added a headless run for fleet workers, replacing ship-mr; user wanted one route to an MR
