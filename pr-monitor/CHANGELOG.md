2026-11-10: Close-out after a merge (ticket, monitor and reviewers, pair helper), run by the caller on any news of a merge; Catch-up no longer waits an hour and runs on every event; --sync and an optional heartbeat; 5-minute pace once the MR looks ready. A merged MR sat 30 minutes with its ticket in-review and its helpers alive
2026-11-09: resolve simple conflicts with the target on its own, as a merge commit pushed without force after tests and a diff-review; anything else still drafts and offers a sync. A one-line conflict where both intents were obvious only got a Draft and an offer
2026-11-08: on t3, a monitor settles its own thread after the final merged/closed event, and Catch-up settles and forgets a dead monitor; a monitor thread stayed unsettled after its MR merged
2026-11-08: on t3, watch the MR with T3's own PR watch, and catch up on MRs that merged after their watch went quiet; an MR merged unwatched and its ticket stayed in-review
2026-11-06: always give the ticket's full link, not its key or title alone (asking, creating, reporting, MR description); user wanted the whole link
2026-11-06: shortened wording, no rule changed; user asked for fewer words
2026-11-06: on t3, archive a finished helper's thread before forgetting it; user saw finished reviewers pile up in the sidebar
