2026-11-11: a review runs in one fresh reviewer thread through session-manager, which reports and settles itself; the caller verifies the findings and cleans up. User wanted reviews off the main thread and the thread closed when done
# diff-review changelog

- 2026-11-09: new Layers and phases lens: a phase-named step that branches on a platform or provider value already dispatched elsewhere, or a field that only carries state between two functions; Parity's single-`if` exemption no longer covers a value dispatched elsewhere. Missed by two reviews and a pair review of correct code.
- 2026-11-08: a boolean-returning function reads as a predicate at its call site (`shouldRunCases()`, not `runsCases()`), reported as Minor; from a review comment that renamed such an interface method.
- 2026-11-04: a timing-dependent test waits on a condition (every backend blocked behind the holder), not on which statement blocks. The race test filtered waiters by query text and flaked in CI.
2026-11-06: shortened wording, no rule changed; user asked for fewer words
2026-11-06: lenses now cover discoverable inputs, flags with no caller, repeated branching on one value, names that hide what code does, and layout vs sibling modules; a reader or maintainer cost counts as a scenario, capped at Should fix; a human reviewer caught these by hand
