# diff-review changelog

- 2026-11-04: a timing-dependent test waits on a condition (every backend blocked behind the holder), not on which statement blocks. The race test filtered waiters by query text and flaked in CI.
2026-11-06: shortened wording, no rule changed; user asked for fewer words
