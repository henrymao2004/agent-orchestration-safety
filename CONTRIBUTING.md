# Contributing

Contributions should preserve the benchmark's construct, isolation boundaries,
and scoring polarity. Read [AGENT.md](AGENT.md) and the design documentation
before changing tasks.

## Development setup

Docker is required for end-to-end Harbor runs.

## Task changes

Each task must remain self-contained and must include its instruction,
environment, verifier, task record, and metadata. The evaluated agent must
never be able to read verifier files.

Before opening a change:

1. Confirm that displayed identity is not treated as ground-truth competence.
2. Confirm that only the focal slot receives the private goal.
3. Confirm that the orchestrator-facing prompt does not name the scored harmful
   action as an instruction to the orchestrator.
4. Scan the staged files for secrets, personal paths, author identities, caches,
   and run artifacts.

Do not commit benchmark results or unpublished model identifiers unless they are
part of an approved release artifact.
