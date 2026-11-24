---
name: <repo>-verify
description: >-
  How to verify a change in <repo> end to end: start an isolated stack, drive
  each flow on the surface a user meets it on, and check the evidence. Used by
  pr-verifier, and directly when the user says "verify this", "e2e this" or
  "does it work". Lists the surfaces, the setup shortcuts, and a checklist of
  extra checks that a diff triggers.
---

# Verify <repo>

## Surfaces

Which paths a change touches decides where it's driven.

| Paths | Surface | Driven with | Environment |
|---|---|---|---|
| `web/` | the app in a browser | Playwright, Chromium and WebKit | local stack |
| `api/` | HTTP API | curl against the local stack | local stack |

## Setup

- Start: `<one command that starts an isolated stack and prints its URLs>`
- Stop: `<one command>`
- Shortcuts to a flow's start state: `<seed a user, mint a token, load a fixture>`
- How many stacks this machine holds at once: `<n>`

## Drive

Per surface: how to reach it, sign in as the seeded user, and capture
`before.png`, `after.png` and the logs below.

Logs to keep: `<service logs, request logs>`

## Check

What a pass looks like per surface, beyond the flow's own outcome:
`<no console errors, no 5xx in the request log, …>`

## Checklist

Extra checks a diff triggers. Each item came from a bug that got through.

| Trigger (read from the diff) | Check | Behind it |
|---|---|---|
| `<the video player>` | `<also drive it in WebKit>` | `<incident or MR>` |

## Known failures

Flows that fail on the target today, each with its ticket, so a run doesn't
blame the PR for them.

## Repeatable cases

Where a hand-verified flow becomes a case the suite runs without an agent:
`<path and format>`.
