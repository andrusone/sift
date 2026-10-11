# Operating Model

Three roles: a **product owner** (human), an **architect** (Claude Sonnet 5.5), and **coding agents** (GitHub Copilot / GPT-6 Luna). The model is generic. Product, stack and domain safety rules are filled in per project.

## 1. Roles and contracts

| Role | Owns | Does not |
|---|---|---|
| Product owner | Functional requirements, customer value (the Value number), priority, UAT acceptance, the retro | Answer technical or spec questions from agents |
| Architect | Technical requirements, the spec, estimates (1, 2, 3, 5, 8; 8 or more is split), PR review, answering agent questions, merging, setting Done | Code, except small housekeeping on a branch |
| Coding agent | One story at a time (or a chain of up to three), tests, PR, honest reporting | The spec (except traceability rows and dependency pins), guardrail files, merging, setting Done |

Score = Value / Estimate. It orders the queue, subject to dependencies.

Agents never ask the owner a spec question. They ask on the card, set `Waiting on: Architect`, take the safest default and keep going.

## 2. Artifacts

- **Spec**: `docs/SPEC.md` plus one file per area under `docs/spec/`. Versioned only in `SPEC.md`, one changelog row per change. Requirements have IDs, acceptance and named tests; rules that matter get a guard (static test). MAJOR/MINOR/PATCH; while major is 0, a contract change bumps MINOR.
- **Board** (GitHub Projects v2): Backlog, Preparing, Ready, In progress, Blocked, Done. Fields: Estimate, Value, Score, Sprint, Waiting on. Milestones are product increments.
- **Cards**: outcome form. Why it matters, acceptance you can see, assumptions, spec links, exact `Depends on`, agent notes. Acceptance describes outcomes, not implementation.
- **Sprint log**: one pinned issue with a check-in comment each time the architect looks, plus metrics.
- **Decision issues**: for questions the spec does not already answer.

## 3. Flow

1. **Backlog**: the owner captures a need in functional terms and sets Value.
2. **Preparing**: the architect adds acceptance, spec links, dependencies, agent notes and an estimate. If the spec needs a requirement, a spec-only PR merges first. A card is **Ready** only when it has no open question, a Value, every dependency merged or earlier in the same chain, and an estimate of 5 or less.
3. **Ready** is an ordered queue grouped in threes. Within a group each story stacks on the previous branch. The next group starts once the last story of the previous group is merged. Read each card's `Depends on` before naming a chain.
4. **Agent session**: one line: "read the starter prompt from origin/main and implement stories #A, then #B, then #C." The agent works in worktrees, never touches main, comments on the card at start, on each decision and on each blocker, and stops at the first blocker, failed check or guardrail file.
5. **Review**: the architect reads the diff and tests from a fresh context. Verdict is `MERGE` or `CHANGES REQUESTED`. Merge needs green CI on every gated platform plus the verdict. The architect merges in order and sets Done. Guardrail files (workflows, branch protection, skills) wait for the owner.
6. **Sprint rhythm**: planning, daily check-in ("check the sprint"), UAT by the owner on a real build, retro with metrics.

## 4. Principles

- **Observable**: every assumption, decision, blocker and question is on the card or a Decision issue. Nothing lives only in a chat.
- **Stop and ask, don't guess**: unmarked guesses are findings.
- **Safety by tests, not trust**: see `SAFETY.md`.
- **Verify honestly**: each PR states what ran in the real app versus fixtures, and what the owner must check in UAT. A unit test with a mock is not proof.
- **Independent oracles for numbers**: expected figures come from a separate computation, not the code under test.
- **Cost awareness**: CI minutes are budgeted with a hard stop; docs-only changes skip CI; stale runs are cancelled.

## 5. Working rules

- Chains: three stories maximum, stacked, merged in order.
- Agents never set Done and never commit screenshots.
- When writing a requirement, check it against its neighbours for conflicts.
- CI that fails in seconds with no steps is almost always billing or quota, not code. Read the annotation first.
- The agent's main checkout stays on `main` and clean. Generated files are restored before switching branches.
- Windows/PowerShell traps: `Rd` is an alias; function output mixed into returned strings corrupts edits. Use real string functions and verify after editing.
- A Decision issue is not needed when the spec already answers the question.

## 6. Metrics to collect

This model prescribes what to collect. It holds no baselines; those come later.

- **Per story**: estimate, cycle time (Ready to Done), review rounds, first-pass `MERGE` (yes/no), split after Ready (yes/no).
- **Per agent session**: blockers raised, questions asked, unmarked guesses found in review, guardrail-file stops, failed CI runs before green.
- **Per sprint**: stories and points completed, UAT defects, spec changes by MAJOR/MINOR/PATCH, CI minutes against budget, owner-raised changes after Ready, retro actions opened and closed.

## 7. Prompts

The architect writes the agent prompts (`STARTER_PROMPT.md`, `.github/copilot-instructions.md`) for the coding agents. Process rules and safety rules live in separate files so each project can state its own safety rules. `PROMPT-AUTHORING.md` records the conventions so changing agent or model means revising prompts, not this model.

## 8. First hour

1. Create the repo from this template; run `tools/github/bootstrap` (board, fields, labels, settings, branch protection, sprint log).
2. Run `tools/discovery` on the machine, then `tools/setup` for the stacks the project uses.
3. Fill the placeholders in `SPEC.md` and `SAFETY.md`.
4. Set the CI minutes budget and hard stop.
5. Require the `gate` check in branch protection once CI exists.
6. Owner adds first stories to Backlog with Value; architect prepares the first chain.
7. Run the first story and review it.
