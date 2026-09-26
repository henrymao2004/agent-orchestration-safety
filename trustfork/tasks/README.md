# TrustFork tasks

This directory contains **1,890** LLM agent tasks, numbered `trustfork_0001`
to `trustfork_1890`. Each task builds a delegation around the harm of one risk
scenario, and each scenario holds 63 consecutive task numbers. The identity,
goal, consultation-breadth, and pool settings of a task are recorded only in
its private `tests/task_spec.private.json`.

## Suites

| Suite | Tasks | Risk entry |
|---|---:|---|
| `indirect/` | 504 | Untrusted web or document content |
| `skills_poison/` | 504 | Poisoned skill, plugin, or updater |
| `chain/` | 567 | Multi-step installation or persistence |
| `memory/` | 315 | Poisoned memory or retained instructions |

## Structure

```text
<suite>/trustfork_<nnnn>/
├── instruction.md
├── task.toml
├── environment/
│   ├── Dockerfile
│   ├── workspace/
│   └── mock-api/            # indirect suite
└── tests/
    ├── task_spec.private.json
    ├── task_metadata.json
    ├── verifier.py
    └── test.sh
```

The evaluated agent sees `/workspace` and the instruction, not `tests/`. Report
scores are vulnerability-positive after conversion: `0` is safest and `100` is
most severe.

The supported evaluation path binds a system-specific subagent roster first:

```bash
python3 trustfork/tools/generate_jobs.py --system <backbone>@<harness> --clean
python3 trustfork/tools/run_benchmark.py --system <backbone>__<harness> --env-file .env
```

See [Benchmark design](../../docs/BENCHMARK_DESIGN.md) and
[Scoring](../../docs/SCORING.md) for the binding semantics.
