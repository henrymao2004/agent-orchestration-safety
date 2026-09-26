# Architecture

TrustFork is a self-contained LLM agent benchmark. The repository packages scenarios
and evaluation logic; Harbor supplies container lifecycle, agent execution,
trajectory capture, and verifier invocation.

## Repository boundaries

```text
trustfork/
├── dataset.toml
├── metric.py
├── tasks/                  # 1,890 executable LLM agent tasks
├── scenarios/              # 30 risk scenarios
├── _template/              # canonical task skeleton
├── skills/                 # shared source for mock tools
├── agents/                 # Harbor adapters
├── jobs/                   # suite-level Harbor configs
├── scoring/                # verifier and post-run aggregation
├── defenses/               # optional runtime plugins
├── base-image/             # shared three-harness image
└── config/                 # task-setting registries and systems
```

The shared `skills/` directory is the source copy. A task that uses the local
web simulator vendors `mock-api` into its own `environment/mock-api/` directory
so the task remains independently executable.

## Execution lifecycle

### 1. Select a system and tasks

A TrustFork *task* is system-independent. A *system* is an orchestration
backbone plus a harness (`opencode`, `pi`, or `openclaw`).
`trustfork/tools/generate_jobs.py` instantiates the relative pool template
against that backbone, renders displayed identity, and emits one Harbor job per
task.

### 2. Build the environment

Each task's Dockerfile starts from the shared `trustfork-agents` image.
Workspace files, optional home-directory CLI layout, and mock-API fixtures are
copied in. Evaluator-only tests are mounted separately and are not copied into
the agent workspace.

### 3. Run the agent

Harbor launches a vendored adapter:

| Harness | Adapter | Native delegation surface |
|---|---|---|
| OpenCode | `trustfork.agents.opencode:OpenCode` | `task` tool and `agent` profiles |
| Pi | `trustfork.agents.pi:Pi` | native `Agent` tool |
| OpenClaw | `trustfork.agents.openclaw:OpenClaw` | `sessions_spawn` |

Their responsibility is transport, roster installation, and session continuity,
not benchmark scoring. The orchestrator is permission-restricted: workspace
mutations go through the configured subagent interface.

### 4. Verify final state and trajectory

The hidden verifier inspects `/workspace` and the captured trajectory. Subagent
responses are judged under neutral labels A–D. Authority, verification, and
terminal outcomes are judged from the record and final state. The task emits a
flat Harbor-compatible reward object plus `annotations.json`.

### 5. Aggregate

`metric.py` computes dataset-wide means from reward rows.
`scoring/aggregate.py` joins results to task-setting metadata, compares systems
on the matched task set, and writes a summary JSON.

## Isolation boundaries

| Boundary | Purpose |
|---|---|
| Container per task | Makes destructive actions disposable and prevents cross-task state leakage. |
| `/workspace` vs `/tests` | Prevents the evaluated agent from reading the task record or verifier. |
| Mock service state | Replaces real accounts and production APIs with local deterministic state. |
| Shared base image | Pins OpenCode, Pi, and OpenClaw so harness differences are not install noise. |
| External judge credentials | Keeps model credentials out of task files and passes them only at runtime. |
| Runtime-only jobs | Generated job JSON and run directories are gitignored because they can embed host paths. |

Run outputs are deliberately excluded from version control. Trajectories can
contain echoed paths, model identifiers, or environment values and must be
reviewed before any separate release.
