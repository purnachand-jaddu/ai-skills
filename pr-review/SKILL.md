---
name: pr-review
description: >-
  Review a pull request / merge request by handing it to the diff-review skill:
  the PR/MR number, URL or branch becomes diff-review's target, and diff-review
  does all the work and reporting. Use when the user says "pr-review", "review
  PR 12", "review MR 858", "review this PR" or pastes a PR/MR link to review.
  Read-only, like diff-review.
---

# PR review

Load the `diff-review` skill and run it with the PR/MR as its target (number,
URL or branch, as given). Follow it as written; this skill adds nothing to it.

No PR/MR given: let `diff-review` find the one for the current branch.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
