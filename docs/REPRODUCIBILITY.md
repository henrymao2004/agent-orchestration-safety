# Reproducibility

This document describes the minimum information needed to reproduce a TrustFork
run without publishing credentials, private trajectories, or machine-specific
paths.

## Requirements

- Python 3.12 or newer for the repository tooling; individual task containers
  pin their own runtime
- Docker with enough capacity to build the shared agent image and task images
- Harbor on `PATH`, or `HARBOR_BIN` pointing at a Harbor executable
- Provider credentials for the evaluated system
- A DeepSeek API key for the DeepSeek-V4-Flash trajectory judge

Install Harbor using its documented CLI distribution:

```bash
uv tool install harbor
harbor run --help
docker info
```

## Runtime configuration

Copy [`.env.example`](../.env.example) and supply values locally. The
trajectory judge reads the following variables at runtime:

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | Judge credential |
| `GLM_API_KEY`, `MINIMAX_API_KEY`, `KIMI_API_KEY`, `OPENAI_API_KEY` | Evaluated-system providers declared in `trustfork/config/systems.yaml` |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible gateway |

Pass secrets through Harbor's verifier and agent environment. Do not write them
into task files, job configs, shell history committed to the repository, or
result archives.

Pinned harness versions:

| Harness | Version |
|---|---|
| OpenCode | 1.18.13 |
| Pi | 0.84.1 (`@tintinweb/pi-subagents@0.15.0`) |
| OpenClaw | 2026.7.1-2 |

The shared image tag is `trustfork-agents:tf-three-harnesses-v1`.

## Run one system

```bash
python3 trustfork/tools/ensure_base_image.py
python3 trustfork/tools/generate_jobs.py --system glm-5.2@opencode --clean
python3 trustfork/tools/run_benchmark.py \
  --system glm-5.2__opencode \
  --workers 4 \
  --env-file .env
```

`run_benchmark.py` keeps a durable ledger under `build/`, resumes unfinished
Harbor jobs, and skips clean completions, so rerunning is incremental.

Optional runtime defenses are generated as isolated systems:

```bash
python3 trustfork/tools/generate_jobs.py \
  --system minimax-m3@opencode \
  --defense anonymize-responses \
  --clean
python3 trustfork/tools/run_benchmark.py \
  --system minimax-m3__opencode__def-anonymize-responses \
  --env-file .env
```

See `trustfork/defenses/` for the three plugins and their audit contract.

## Run record

For every reported run, retain the following in a private experiment ledger:

- TrustFork commit hash and task subset
- Harbor version and Docker version
- System id (backbone × harness × optional defense)
- Judge model and model family
- Worker count and timeout settings
- Number of attempted, scored, invalid, and unmeasurable trials
- Aggregator command and output

Do not publish the ledger until it has passed an anonymity and credential
review.

## Determinism

- Task environments and mock-service state are vendored with each task.
- Risk scenarios are vendored under `trustfork/scenarios/canary/` with their
  original licenses.
- Pool templates are relative; concrete backbones are rendered from
  `trustfork/config/systems.yaml`.
- C1-style terminal checks read the workspace. Trajectory judges can vary with
  provider-side model updates; record exact judge identifiers and dates.
- Do not commit generated jobs. They can embed host-relative paths and should
  be regenerated from the tools.

## Release hygiene

The repository intentionally excludes `jobs/`, `runs/`, `results/`, `build/`,
caches, logs, environment files, and archives. Before packaging a supplementary
artifact:

1. Export from a clean commit rather than zipping a working directory.
2. Exclude `.git`, `.DS_Store`, caches, virtual environments, logs, and trajectories.
3. Scan the archive itself for credentials, emails, personal paths, author
   identities, and remote URLs that reveal the authors.
4. Verify checksums and inspect the final archive member list.
