# TrustFork dataset package

This directory contains the executable LLM agent benchmark. For benchmark motivation,
setup, badges, and citation information, start with the repository-level
[README](../README.md).

## Contents

| Path | Purpose |
|---|---|
| `dataset.toml` | Dataset identity and Harbor metric registration |
| `metric.py` | Dataset-wide RTF, RSR, IAS, SAF, VF, EI, TH, and TUL metrics (0–100, all lower-is-better) |
| `tasks/` | 1,890 tasks grouped by source suite |
| `scenarios/` | 30 vendored risk scenarios |
| `_template/` | Reusable task skeleton |
| `skills/` | Shared mock services |
| `agents/` | Specialized Harbor agent adapters |
| `jobs/` | Full-suite and per-suite job configurations |
| `scoring/` | Verifier, recovery, and stratified aggregation |

## Run

From the repository root:

```bash
# Bind the four-candidate roster to one evaluated system
python3 trustfork/tools/generate_jobs.py --system glm-5.2@opencode --clean

# Run
python3 trustfork/tools/run_benchmark.py --system glm-5.2__opencode --env-file .env

# Post-run metrics
python3 trustfork/scoring/aggregate.py --results jobs --out metrics.json
```

Verifier credentials must be supplied at runtime. See
[Reproducibility](../docs/REPRODUCIBILITY.md) for the required environment and
[Scoring](../docs/SCORING.md) for metric definitions.
