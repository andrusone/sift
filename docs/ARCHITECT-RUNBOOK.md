# Architect runbook

For the architect (Claude). The operating model is in `OPERATING-MODEL.md`; this is how to run it day to day. Everything observable lives on the card, a Decision issue or the sprint log; nothing lives only in a chat.

## Preparing a card

A card moves Backlog → Preparing → Ready. It is **Ready** only when all of these hold:

- [ ] It is written in outcome form (template below) and acceptance describes outcomes, not implementation.
- [ ] Every linked spec requirement exists and has been checked against its neighbours.
- [ ] `Depends on` lists exact card numbers; each is merged, or earlier in the same chain.
- [ ] The owner has set **Value**.
- [ ] You have set **Estimate** (1, 2, 3, 5, 8). Anything 8 or more is split. Ready means 5 or less.
- [ ] No open question. If the spec answers a question, link the requirement; a Decision issue is only for questions the spec does not answer.

If the card needs a requirement the spec lacks, write it first and merge a spec-only PR (`type:spec`), then mark the card Ready.

Set **Score** = Value / Estimate. Order the Ready queue by Score, subject to dependencies.

### Card template

```
**Why it matters:** the outcome for the user, in functional terms.
**Acceptance:** what can be seen when it works.
**Assumptions:** what is taken as true (agents add theirs as comments).
**Spec:** links to requirement IDs.
**Depends on:** #n, #m (or "none").
**Agent notes:** pointers that save time; constraints; where to look.
```

## Chains

- Group the Ready queue in threes. Within a group each story stacks on the previous branch.
- Before naming a chain, read each card's `Depends on` line. Put dependencies first.
- Start the next group only when the last story of the previous group is merged.
- Session line: `read the starter prompt from origin/main and implement stories #A, then #B, then #C.`

## Answering agent questions

Agents ask on the card and set `Waiting on: Architect`. Answer on the card. Never forward a spec question to the owner. If the answer is a new requirement, write it into the spec and say so on the card.

## Review

Read the diff and the tests from a fresh context.

1. Does it do what the card's acceptance says, and nothing else?
2. Are the spec requirements and their named tests present and meaningful?
3. Does the PR say honestly what ran in the real app versus fixtures? A mock is not proof.
4. Are all assumptions and guesses on the card? An unmarked guess is a finding.
5. Do the safety guards still pass? Does anything touch a guardrail file? If so it waits for the owner.
6. Were the numbers checked against an independent oracle?

Verdict: **MERGE** or **CHANGES REQUESTED**, with reasons. Merge needs green CI on every gated platform plus your verdict. Merge in order, then set the card Done. Agents never set Done.

## CI failures

- A run that fails in seconds with **no steps** is almost always billing or quota, not code. Read the run annotation first.
- Otherwise read the failing step. Do not re-run blindly.

## Spec changes

Spec-only PR, one changelog row, version bump per `SPEC.md`. Check the new requirement against its neighbours before merging.

## Sprint rhythm

- **Planning:** pick the Ready cards for the sprint; confirm Values and estimates.
- **Check-in** (when the owner says "check the sprint"): comment on the sprint log with the date, what merged, what is in progress, blockers, questions waiting, and CI minutes used against the budget.
- **UAT:** the owner runs a real build against each PR's UAT list.
- **Retro:** review the metrics in `OPERATING-MODEL.md`, agree actions, open cards for them.

## Housekeeping you may do on a branch

Small fixes to docs, traceability rows and the like. Not code. Guardrail files wait for the owner.

## Traps

- PowerShell: `Rd` is an alias, and function output mixed into a returned string corrupts edits. Use real string functions and verify after editing.
- The agent's main checkout must stay on `main` and clean. Restore generated files before switching branches.
