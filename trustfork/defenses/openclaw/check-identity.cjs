const { appendFileSync, mkdirSync } = require("node:fs")

const MANIFEST = Object.freeze(__TRUSTFORK_DEFENSE_MANIFEST__)
const PLUGIN_ID = "trustfork-defense-check-identity"
const LOG_DIR =
  process.env.TRUSTFORK_DEFENSE_LOG_DIR || "/logs/agent/openclaw/defense"
const LOG_PATH = `${LOG_DIR}/events.jsonl`
const ACTORS = new Map(MANIFEST.actors.map((actor) => [actor.profile, actor]))

function audit(event, fields = {}) {
  mkdirSync(LOG_DIR, { recursive: true })
  appendFileSync(
    LOG_PATH,
    `${JSON.stringify({
      schema_version: "trustfork-defense-event-v1",
      timestamp: new Date().toISOString(),
      defense: MANIFEST.defense,
      system_id: MANIFEST.system_id,
      task_id: MANIFEST.task_id,
      event,
      ...fields,
    })}\n`,
  )
}

// Derived only from the trusted provider/model mapping. The adapter publishes
// the same text as each candidate's visible name and description.
function attestation(actor) {
  const actual = actor.actual_identity
  return [
    `Subagent ${actor.slot}`,
    `verified model ${actual.display_model}`,
    `provider ${actual.provider}`,
    `${actual.family} family`,
    `${actual.tier} tier`,
  ].join("; ")
}

function expectedModelRef(actor) {
  return `${actor.actual_identity.provider}/${actor.actual_identity.api_model}`
}

function displayMatchesActual() {
  if (MANIFEST.identity_display_id === "M0") return null
  return ["M1", "M3", "M5"].includes(MANIFEST.identity_display_id)
}

function identityFields(actor) {
  return {
    profile: actor.profile,
    slot: actor.slot,
    displayed_identity: actor.displayed_identity,
    verified_provider: actor.actual_identity.provider,
    verified_model: actor.actual_identity.api_model,
    display_matches_actual: displayMatchesActual(),
    identity_claim_status: MANIFEST.identity_claim_status,
  }
}

function runtimeIdentity(ctx, event = {}) {
  const resolved = event.resolvedModel || null
  if (typeof resolved === "string" && resolved.includes("/")) {
    const slash = resolved.indexOf("/")
    return {
      provider: resolved.slice(0, slash) || null,
      model: resolved.slice(slash + 1) || null,
    }
  }
  return {
    provider:
      ctx.modelProviderId || event.resolvedProvider || event.provider || null,
    model: ctx.modelId || event.model || resolved || null,
  }
}

function verifyRoster(api) {
  const entries = Array.isArray(api.config?.agents?.list)
    ? api.config.agents.list
    : []
  const verified = new Set()
  const failures = []
  for (const actor of MANIFEST.actors) {
    const entry = entries.find((item) => item?.id === actor.profile)
    const expectedModel = expectedModelRef(actor)
    const expectedName = attestation(actor)
    const expectedDescription = `${expectedName}.`
    let reason = null
    if (!entry) reason = "missing_profile"
    else if (entry.model !== expectedModel) reason = "runtime_model_mismatch"
    else if (
      entry.name !== expectedName ||
      entry.description !== expectedDescription
    ) {
      reason = "attestation_not_published"
    }
    if (reason) {
      failures.push(`${actor.profile}:${reason}`)
      audit("identity_check_failed", {
        ...identityFields(actor),
        reason,
        configured_model: entry?.model ?? null,
        expected_model: expectedModel,
        configured_name: entry?.name ?? null,
        configured_description: entry?.description ?? null,
      })
      continue
    }
    verified.add(actor.profile)
    audit("identity_checked", {
      ...identityFields(actor),
      attestation: expectedName,
    })
  }
  return { verified, failures }
}

module.exports = {
  id: PLUGIN_ID,
  name: "TrustFork Check Identity",
  register(api) {
    audit("plugin_initialized", {
      manifest_schema_version: MANIFEST.schema_version,
    })

    // Any mismatch rejects the whole roster, so every spawn and child run is blocked.
    const roster = verifyRoster(api)
    const rosterRejected = roster.failures.length > 0
    const verifiedProfiles = rosterRejected ? new Set() : roster.verified
    if (rosterRejected) {
      audit("roster_identity_rejected", {
        checked_profiles: MANIFEST.actors.length,
        failures: roster.failures,
      })
    } else {
      audit("roster_identity_attested", {
        checked_profiles: verifiedProfiles.size,
      })
    }

    api.on("before_tool_call", (event, ctx) => {
      if (String(ctx.agentId || "") !== "main") return
      if (event.toolName !== "sessions_spawn") return
      const profile = String(event.params?.agentId || "")
      const actor = ACTORS.get(profile)
      if (!actor || !verifiedProfiles.has(profile)) {
        audit("identity_check_failed", {
          session_id: ctx.sessionId || null,
          session_key: ctx.sessionKey || null,
          call_id: event.toolCallId || null,
          profile: profile || null,
          reason: !actor
            ? "unknown_profile"
            : rosterRejected
              ? "roster_rejected"
              : "unverified_profile",
        })
        return {
          block: true,
          blockReason: `TrustFork identity check rejected unverified profile: ${profile}`,
        }
      }
      audit("identity_check_passed", {
        ...identityFields(actor),
        session_id: ctx.sessionId || null,
        session_key: ctx.sessionKey || null,
        call_id: event.toolCallId || null,
      })
    })

    // Gate every child run before inference on its resolved provider/model.
    api.on("before_agent_run", (event, ctx) => {
      const profile = String(ctx.agentId || "")
      const actor = ACTORS.get(profile)
      if (!actor) return
      const actual = runtimeIdentity(ctx, event)
      const fields = {
        ...identityFields(actor),
        stage: "before_agent_run",
        session_id: ctx.sessionId || null,
        session_key: ctx.sessionKey || null,
        run_id: ctx.runId || null,
        actual_provider: actual.provider,
        actual_model: actual.model,
      }
      let reason = null
      if (!verifiedProfiles.has(profile)) reason = "unverified_profile"
      else if (!actual.provider || !actual.model) reason = "runtime_identity_unresolved"
      else if (
        actual.provider !== actor.actual_identity.provider ||
        actual.model !== actor.actual_identity.api_model
      ) {
        reason = "runtime_request_mismatch"
      }
      if (reason) {
        audit("identity_check_failed", { ...fields, reason })
        return {
          outcome: "block",
          reason: "trustfork_identity_mismatch",
          message:
            "TrustFork identity verification rejected this child runtime model.",
        }
      }
      audit("identity_runtime_verified", fields)
      return { outcome: "pass" }
    })

    api.on("subagent_spawned", (event, ctx) => {
      const profile = String(event.agentId || "")
      const actor = ACTORS.get(profile)
      if (!actor) return
      const actual = runtimeIdentity(ctx, event)
      audit("identity_spawn_observed", {
        ...identityFields(actor),
        stage: "subagent_spawned",
        session_id: ctx.sessionId || null,
        session_key: ctx.sessionKey || event.childSessionKey || null,
        actual_provider: actual.provider,
        actual_model: actual.model,
        verified_profile: verifiedProfiles.has(profile),
      })
    })
  },
}
