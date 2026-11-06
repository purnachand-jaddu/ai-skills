---
name: skill-improve
description: >-
  Improve one of the user's own skills when its output missed: find the skill
  that produced it, decide whether the feedback belongs in that skill (or in
  memory, a repo's CLAUDE.md, or nowhere), turn the complaint into a general
  rule, and propose the smallest edit as a diff applied only on the user's yes.
  Then offer to redo the task. Use when the user says "that's not what I
  wanted", "the skill got this wrong", "improve the skill", "update pr-raise so
  it…", "fix the skill", "skill-improve", or shows they are unhappy with what a
  skill just did. Never edits built-in, plugin or repo-committed skills.
---

# Skill improve

You fix the skill, not just the output. The danger is overfitting: a skill
rewritten around one bad run becomes a patch for that case and worse at the
rest. Generalise first, then edit as little as possible.

## Ground rules

- **Diff first, yes second.** Show the exact diff and apply it only on the
  user's yes. A skill changes future behaviour everywhere it runs.
- **Only the user's own skills:** `~/codebase/ai-skills/<name>/`. Built-in and
  plugin skills are not editable. A repo's `.agents/skills/` is committed: hand
  the change to `pr-raise` as an MR instead.
- **One complaint, one rule.** Don't use the edit to tidy unrelated parts of the
  skill; mention anything else you noticed.
- Match the skill's existing voice, layout and length. Comments in examples
  stay one line.

## 1. Find the skill

The skill whose output the user is unhappy with: the most recent skill launch
in this conversation that produced it. Several ran (a chain like pr-raise →
ticket-manager): name the one where the miss happened and say why; ask if it's
unclear. Read its whole `SKILL.md` and any file it points to.

## 2. Decide where the feedback belongs

| The feedback is about | Do |
|---|---|
| the skill's procedure: a wrong step, a missing step, a rule it skipped, a bad default | edit the skill (continue) |
| this one task only ("not this time", a one-off preference) | no edit; redo the task |
| how Claude works in general (tone, comments, git habits) | a memory, not the skill; say so and offer it |
| a fact about a repo | that repo's `CLAUDE.md`, through an MR |
| a skill that already says the right thing and wasn't followed | no new rule; make the existing one harder to miss (move it up, bold it, put it in Ground rules) |

The last row matters: adding a second copy of a rule that was ignored makes the
skill longer, not better.

## 3. Generalise

Restate the complaint as a rule: **"when X, do Y, because Z"**. Test it:

- Would it have produced the right output this time?
- Does it hold for the other cases the skill covers, not just this one?
- Does it contradict another rule in this skill, or in a skill it calls or is
  called by? Read those too.

Show the user the rule in one line before the diff, so a wrong reading is caught
cheaply.

## 4. Propose the edit

The smallest change that carries the rule, in the right section (a ground rule,
a step, a table row, a failure mode). Update the frontmatter `description` only
if the skill's triggers or scope changed.

Show it as a unified diff (`diff -u` of the file and the proposed copy in the
scratchpad). On a yes, apply it; on a "no, more like…", revise and show again.

## 5. Record and redo

- Append one line to `<skill>/CHANGELOG.md`: date, the rule, the complaint in a
  few words. Create the file if missing.
- Offer to redo the original task with the updated skill. Reload it first, since
  the loaded copy in this conversation is the old one.

## Report

```
pr-raise: added rule "when the target isn't main, ask before linking a ticket" (Ground rules)
Diff applied · logged in pr-raise/CHANGELOG.md · redo the MR now?
```

## Failure modes

- **Same complaint already in the CHANGELOG:** the earlier fix didn't work. Say
  so, and look for why (wrong section, ignored rule, conflicting rule) before
  adding anything.
- **Skill past ~200 lines:** propose consolidating it instead of adding another
  rule.
- **Feedback contradicts a rule the user set earlier** (in the skill, a memory
  or a CLAUDE.md): name both and ask which wins; don't pick silently.
- **The miss came from a tool or environment** (auth, a blocked fetch, a crash),
  not the skill: no skill edit; fix or report the environment.
