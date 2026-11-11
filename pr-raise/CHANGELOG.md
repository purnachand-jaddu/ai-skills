2026-11-11: the create guard also catches bash/sh -c and wrappers with their arguments (env -u, sudo -u, timeout 60), and skips heredoc bodies written as data while still checking the heredoc's own line; a review found both gaps
2026-11-11: the only way to open an MR, one run per MR in a batch; step 5's creates carry PR_RAISE=1 and a PreToolUse hook (hooks/mr_create_guard.py) blocks any other `glab mr create` / `gh pr create`. A coordinator opened 8 MRs by hand and none got a pr-monitor
2026-11-11: runs one diff-review of the MR's changes before the plan and names its report in pr-monitor's first message; reviews start here, in pr-monitor and pr-takeover, or on request, not before every push. User saw three reviewer threads for one push
2026-11-11: removed the headless run for fleet workers; the agent fleet skills were removed
2026-11-06: always give the ticket's full link, not its key or title alone (asking, creating, reporting, MR description); user wanted the whole link
2026-11-06: shortened wording, no rule changed; user asked for fewer words
2026-11-06: added a headless run for fleet workers, replacing ship-mr; user wanted one route to an MR
