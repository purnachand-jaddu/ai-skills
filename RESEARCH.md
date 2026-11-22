# Research

How to research a question before answering it or building on it. Verify, don't recall.

## When to research

- Anything that changes over time is checked live, never quoted from memory: prices, quotas, versions, licences, project activity
- Before accepting a costly tradeoff (CGO, a new dependency, a slower path), look for an alternative; a quick search often settles it
- Before building, settle feasibility: is it possible, does it work on macOS, Linux and Windows, does it add CGO
- When the user states a belief ("I don't think so, but verify"), check it against the code instead of agreeing
- When the user dislikes a solution, look for alternatives, including how established products solve the same problem
- Old findings (an audit, a plan, a past report) are re-checked against current code before anything relies on them

## Sources, best first

- The user's own repo: an existing pattern in a sibling module beats a new one
- The user's real environment: the installed version, the live API, the logs, the deployed instance; not inference about them
- Source code: clone into `~/codebase/opensource` with the `oss-explore` skill, read it, don't run it; a README is a claim until the code confirms it
- Vendor docs, pricing pages, licence texts, changelogs, and the forge API for releases, commits, bus factor and issues
- Published benchmarks only with who ran them; third-party blogs are leads, never the source of a price
- Real data over invented examples: ask the user for real URLs, files or history
- When a site blocks fetching, don't retry it: use search or another source, and cite what was used

## Method

- Use the helper agent the user has named for research; with none, offer one once for long research, otherwise research in this session
  - Parallel helpers only with the user's yes; a helper never starts other agents
- Map the feature in question to the code that does it, end to end and per platform; don't summarise the whole project
- Prove it by running the smallest throwaway program, outside the repo (e.g. `CGO_ENABLED=0` and `=1`, side by side)
- Measure, don't guess: give the number, its unit and the tool that produced it, then rank fixes by measured gain
- Find the root cause before proposing a fix
- Spot-check a helper's claims before passing them on; drop what fails, and say what was dropped
- Ask up front for tools or access the research needs

## Verification

- Every claim carries its source (a URL, `file:line` or command output) and the date it was checked
- Keep what was verified (read in code, run, measured) apart from what is inferred or only claimed
- Never present a number that has no source
- Say what was not checked, and name the probe that would settle it
- Name the version or commit that was read (e.g. the last public tag, when the code went private)
- A claim that no longer holds is reported, not acted on

## Comparing options

- Judge options on the user's criteria: cost in real numbers (per month, minimum commitment), macOS/Linux/Windows support, no CGO, adoption and maintenance health, licence, memory and CPU, the upkeep it adds, and fit with the user's setup
- End with one comparison table, one recommendation for this setup, and what would change it
- Number the options, so the user can answer "go with 2"
- Say what each option can't do
- Product decisions belong to the user: list them as open questions, each with a recommendation

## Reporting

- Verdict first in one sentence, then at most 10 bullets, then the details
- Answer the question that was asked, not a tour of the project
- A helper writes its full result to a file and sends back a one-line verdict with the path
- Research the user will share or keep goes in an artifact (Claude) or a file; findings to act on later become a ticket, with the user's yes

## Boundaries

- Research is read-only: no repo edits, no changes to installed tools or settings, no killing the user's processes
- Throwaway programs live outside the repo
- Anything public (a skill, an upstream issue) keeps company details out
