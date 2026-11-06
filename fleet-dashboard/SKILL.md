---
name: fleet-dashboard
description: Run and expose the agent-fleet web dashboard — live runs, states, costs, MR links, activity feed, and per-run transcripts — and publish it remotely via a cloudflared tunnel. Use when asked to start/stop the dashboard, share it, set up the tunnel, or debug what it shows.
---

# Fleet dashboard

Read-only web UI over `~/.agent-fleet` (runs + `events.jsonl`). Stdlib Python, no build step.

```bash
fleet dashboard                 # = python3 ~/codebase/ai-skills/fleet-dashboard/scripts/server.py
fleet tunnel install            # one-time: install cloudflared (.deb from GitHub releases)
fleet tunnel quick              # throwaway https://<random>.trycloudflare.com URL
fleet tunnel named fleet fleet.example.com   # stable hostname (needs `cloudflared tunnel login` once)
```

- Binds to `127.0.0.1:${DASHBOARD_PORT:-8787}`; only the tunnel exposes it.
- Set `DASHBOARD_TOKEN=<long random>` in `~/.agent-fleet/config.env` before tunnelling. Then open
  `https://<host>/?token=<token>` once; a 30-day HttpOnly cookie is set.
  Generate one with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- For a named tunnel, also put Cloudflare Access (Zero Trust → Applications → self-hosted,
  your email as the allow rule) in front of the hostname. The token is the second layer.
- Read-only by default: nothing reachable through the tunnel can change the fleet.

## Control mode (steer and take over from the browser)
`DASHBOARD_CONTROL=1` in config.env (refused unless `DASHBOARD_TOKEN` is set) adds, for a
selected live run: **Steer now**, **Send after this turn**, **Stop**, **Take over**. Take over
opens a web terminal attached to the run's tmux session.

- The terminal is ttyd, started by the dashboard on a private Unix socket
  (`~/.agent-fleet/ttyd.sock`, mode 600) and reachable only via `/term/` behind the
  dashboard's cookie check. It exits with the dashboard.
- POSTs need the token cookie (SameSite=Strict) and an `X-Fleet-Control: 1` header (CSRF).
- If Cloudflare Access is in front, the steering user's email is recorded on events and
  ticket comments.
- **This is a shell on the machine, as the user running the dashboard.** Only enable it behind a
  named tunnel with Cloudflare Access; never with `fleet tunnel quick`.

## What it shows
- Overview: busy slots, MRs opened, blocked, failed, total spend.
- Runs: state, ticket, tier/model, cost, MR link. Click a run to open its condensed transcript
  (assistant text, tool calls, tool errors, final result), which refreshes live.
- Activity: the event stream (`run.launched`, `run.progress`, `mr.opened`, `run.blocked`, …).

## Keep it running
For something that survives logout, run both under systemd (`fleet dashboard` and
`fleet tunnel named …` as two `Restart=always` services) or in a `screen` session.

## Emitting events
Anything can add to the feed:
`python3 ~/codebase/ai-skills/lib/fleet.py emit <kind> --msg "<text>" [--run ID] [--ticket ID]`.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
