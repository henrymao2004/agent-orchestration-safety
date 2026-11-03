# OpenCode defense plugins

These three plugins implement the TrustFork defense experiment on pinned
OpenCode 1.18.13 without changing benchmark tasks, pools, hidden goals, or the
verifier:

- `anonymize-responses.js` replaces candidate identity descriptions with
  neutral slot labels before the task-tool schema is built.
- `check-identity.js` replaces displayed claims with runtime attestations from
  the job's resolved provider/model roster and validates every delegation.
- `verify-before-action.js` adds a per-subagent evidence gate before mutating
  tools and records whether the gate passed.

`trustfork/tools/generate_jobs.py` replaces the manifest placeholder in the
selected plugin and passes the rendered source to Harbor. Harbor installs only
that file into `~/.config/opencode/plugins/`. Each plugin writes append-only
JSONL audit events to `/logs/agent/opencode/defense/events.jsonl`.

Generate isolated defense conditions:

```bash
for defense in anonymize-responses check-identity verify-before-action; do
  python3 trustfork/tools/generate_jobs.py \
    --system minimax-m3@opencode --defense "${defense}" --clean
done
```

Run one condition with the desired worker count:

```bash
python3 trustfork/tools/run_benchmark.py \
  --system minimax-m3__opencode__def-anonymize-responses \
  --env-file .env --workers 12
```

After a run, require clean Harbor output, the selected plugin's required audit
events, and paired overhead against the matching undefended system:

```bash
python3 trustfork/scoring/audit_defense_run.py \
  --system minimax-m3__opencode__def-anonymize-responses \
  --baseline minimax-m3__opencode --strict \
  --output metrics-defense.json
```

The audit reports agent wall-clock increment, subagent-call increment, and
verification pass-rate increment on task-matched pairs.
