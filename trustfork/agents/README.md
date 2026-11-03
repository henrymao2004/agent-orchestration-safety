# Harbor agent adapters

TrustFork vendors three Harbor installed-agent adapters so evaluation uses each
harness's native delegation interface:

| Module | Class | Native surface |
|---|---|---|
| `trustfork.agents.opencode` | `OpenCode` | OpenCode `task` tool and `agent` profiles |
| `trustfork.agents.pi` | `Pi` | Pi native `Agent` tool |
| `trustfork.agents.openclaw` | `OpenClaw` | OpenClaw `sessions_spawn` |

`trustfork/tools/generate_jobs.py` references these classes through
`import_path`. The adapters install the four-candidate roster, apply the focal
private goal, and preserve native tool schemas. They do not compute benchmark
scores.

Run Harbor from the repository root so `trustfork.agents` is importable, or set
`PYTHONPATH` to the repository root. `trustfork/tools/run_benchmark.py` sets
that path automatically.
