# Production-readiness review checklist

Give this to the independent reviewer along with the PR diff. For each area, the reviewer should either report a concrete finding (file:line, failure scenario, severity, fix) or state "not applicable, because …". Silence is not an answer. Skip areas the change can't plausibly touch, but say so.

Severity:
- **Critical:** data loss, a security hole, a crash on a common path, or the shipped artifact is broken.
- **Important:** a realistic failure, a broken contract or a missing test for changed behaviour.
- **Minor:** style, clarity, unlikely edge cases.

## Correctness
- Does the code do what the PR description claims? Check each claim against the code.
- Edge cases:
  - empty, null and huge inputs;
  - unicode, paths with spaces or special characters;
  - time zones and clock skew;
  - integer bounds.
- Error paths:
  - errors returned or handled, not swallowed;
  - no partial writes left behind;
  - cleanup runs on failure.
- Concurrency:
  - shared state under the right lock;
  - lock ordering;
  - check-then-act races;
  - goroutine, thread or task leaks on shutdown.
- Retries and duplicates: are operations idempotent where they can repeat?

## Callers and contracts
- Every caller of a changed function, type or endpoint is still correct (grep them).
- API, CLI, config and file-format changes are backward compatible, or the break is intended and documented.
- Schema and migration changes:
  - forward-safe on existing data;
  - safe to run twice;
  - rollback considered.

## Security (when it touches input, auth, files, network, secrets, or multi-tenancy)
- Input validated at trust boundaries.
- No injection: shell, SQL, path traversal, markup/HTML, template, prompt.
- Authentication and authorization checked on the new paths.
- Secrets aren't logged, committed, or put in error messages.
- File permissions are right for sensitive files.
- No privilege escalation or confused-deputy paths.

## Tests
- Changed behaviour has tests that assert observable behaviour.
- Bug fixes have a test that fails without the fix.
- Tests are hermetic:
  - no real home dir, user config, network or global state;
  - no sleeps used as synchronisation where an event or channel exists.
- Tests can actually fail: no assertion-free tests and no mocks of the thing under test.

## Operability
- Logs are useful and not noisy, without unbounded growth or log injection from untrusted fields.
- Resource limits:
  - unbounded queues, caches, files or tables;
  - timeouts on network calls.
- Failure is visible to the user: no silent no-op, stuck spinner or misleading success message.
- Deployment and rollback: can this ship and be reverted safely? Are feature flags or migrations ordered correctly?

## Dependencies and build
- New dependencies: justified, licence compatible, maintained, size and transitive cost acceptable, consistent with the repo's dependency policy.
- Builds for every target the project ships (OS/arch matrix, build tags, CGO settings).
- Lockfiles updated consistently.

## Docs and repo conventions
- README, docs, changelog and help text match the new behaviour.
- Comments follow the repo's style.
- No stray debug code, TODOs or commented-out blocks.
- No secrets or local paths in committed files.
