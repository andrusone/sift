# Writing prompts for coding agents

The architect (Claude Sonnet 5.5) writes the prompts that other agents follow: `STARTER_PROMPT.md`, `.github/copilot-instructions.md`, and the per-story agent notes on cards. The current target agents are GitHub Copilot and GPT-6 Luna. Changing the agent or model means revising these conventions' outputs, not the operating model.

## Principles

1. **Say what to do, then what to stop on.** Agents drift when stop conditions are implied. List them.
2. **One rule per sentence, in the imperative.** "Open each PR against the previous branch." Not "PRs should generally be stacked".
3. **Name the files and commands.** An agent cannot ask what "the usual build" is.
4. **Give the reason only when it changes behaviour.** A rule with its cause is applied more correctly at the edges ("CI that fails in seconds with no steps is billing, not code").
5. **Separate process from safety.** Process is in `STARTER_PROMPT.md`; safety is in `SAFETY.md` so each project can state its own.
6. **Prefer checks to exhortation.** If a rule matters, add a guard test; the prompt then says "the guard enforces this".
7. **Ask for honest reporting explicitly,** and say what honest means here: what ran for real, what was mocked, what was guessed.
8. **Keep it short.** Every line costs attention. Cut anything the agent would do anyway.

## Process for a prompt change

1. Write the change as a PR (a guardrail change: needs the owner).
2. State the failure it prevents, from an actual card, PR or review finding.
3. After merge, watch the next session for the behaviour it was meant to change; record the result in the sprint log.

## Per-story agent notes

On the card, under **Agent notes**: where to look, constraints the spec does not cover, known traps, and which commands prove the work. Not a design. Acceptance stays outcome-based.

## Adapting to a different model

Keep the rules; change only phrasing that depends on the model (tool names, how it is started, how it reads repository instructions). Re-run one low-risk story as a trial before trusting it with a chain.
