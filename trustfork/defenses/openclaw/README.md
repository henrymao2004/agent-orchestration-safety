# OpenClaw defense plugins

These three CommonJS plugins mirror the TrustFork OpenCode defense conditions
on OpenClaw 2026.7.1-2 without changing the delegation schema, pool, hidden
goals, routing, or verifier:

- `anonymize-responses.cjs` requires the Harbor adapter's neutralized native
  agent roster and redacts identity-bearing text from parent-session tool
  results and messages before persistence.
- `check-identity.cjs` verifies each roster candidate's configured
  provider/model against the manifest mapping and checks that the candidate's
  visible name and description carry the attestation derived from that
  mapping. Any mismatch rejects the roster: the verified set stays empty and
  every spawn and child run is blocked. `sessions_spawn` is allowed only for
  verified candidates, and native `before_agent_run` blocks every child run
  whose runtime provider/model is unresolved or differs from the mapping.
- `verify-before-action.cjs` injects the same evidence-first instruction into
  candidate prompts and uses native `before_tool_call` / `after_tool_call`
  hooks for a per-session action gate.

`trustfork/tools/generate_jobs.py` replaces the single
`__TRUSTFORK_DEFENSE_MANIFEST__` marker and passes the rendered source and
manifest as `openclaw_trustfork_defense`. Harbor installs it alongside, but
independently from, the existing TrustFork profile-overlay plugin. Events are
append-only JSONL at `/logs/agent/openclaw/defense/events.jsonl`.

The adapter validates the immutable manifest against the configured candidate
roster before setup. `anonymize-responses` additionally neutralizes each
candidate's native `agents.list` name and description before the Gateway builds
the model-visible roster. The plugin fails to register if this precondition is
not present. For `check-identity`, the adapter publishes the attestation
(`Subagent <slot>; verified model <model>; provider <provider>; <family> family;
<tier> tier`) as each candidate's `agents.list` name and description; the plugin
re-derives the same text from the manifest and rejects the roster if it differs.
