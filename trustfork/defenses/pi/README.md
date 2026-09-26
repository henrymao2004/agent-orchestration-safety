# Pi defense extensions

These three inline Pi extensions implement the TrustFork defense conditions
without changing Pi's native `Agent` delegation schema, candidate pool, hidden
goal prompts, or model routing:

- `anonymize-responses.js` neutralizes candidate identity text in the native
  `Agent` tool schema and redacts identity strings from delegation results.
- `check-identity.js` replaces displayed claims in the `Agent` schema with
  manifest-backed attestations, validates selected profiles, and audits each
  child process's actual provider/model against its candidate session path.
- `verify-before-action.js` injects the verification instruction into native
  `Agent` prompts and enforces an evidence-before-mutation gate inside each Pi
  child process.

The generator renders the single `__TRUSTFORK_DEFENSE_MANIFEST__` placeholder
and passes the result through Harbor's `pi_trustfork_defense` agent kwarg. Harbor
installs the rendered source as
`~/.pi/agent/extensions/trustfork-defense.js`. Pi auto-discovers this global
extension in both the root process and native child processes. Audit events are
appended to `/logs/agent/pi/defense/events.jsonl`.
