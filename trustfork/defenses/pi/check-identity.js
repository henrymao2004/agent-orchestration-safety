import { appendFileSync, mkdirSync } from "node:fs"

const MANIFEST = Object.freeze(__TRUSTFORK_DEFENSE_MANIFEST__)
const LOG_DIR = process.env.TRUSTFORK_DEFENSE_LOG_DIR || "/logs/agent/pi/defense"
const LOG_PATH = `${LOG_DIR}/events.jsonl`

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

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

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

function displayMatchesActual() {
  if (MANIFEST.identity_display_id === "M0") return null
  return ["M1", "M3", "M5"].includes(MANIFEST.identity_display_id)
}

function attestText(text) {
  let value = String(text ?? "")
  for (const actor of MANIFEST.actors) {
    if (!actor.displayed_identity) continue
    value = value.replace(
      new RegExp(escapeRegExp(actor.displayed_identity), "gi"),
      attestation(actor),
    )
  }
  return value
}

function attestValue(value) {
  if (typeof value === "string") return attestText(value)
  if (Array.isArray(value)) return value.map(attestValue)
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, attestValue(item)]),
    )
  }
  return value
}

function toolName(tool) {
  return tool?.name ?? tool?.function?.name ?? null
}

function attestAgentTool(payload) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.tools)) {
    return null
  }
  let found = false
  const tools = payload.tools.map((tool) => {
    if (toolName(tool) !== "Agent") return tool
    found = true
    return attestValue(tool)
  })
  return found ? { ...payload, tools } : null
}

function profileFromSession(ctx) {
  const sessionFile = ctx.sessionManager.getSessionFile?.() ?? ""
  return MANIFEST.actors.find((actor) =>
    new RegExp(`(?:^|/)${escapeRegExp(actor.profile)}(?:/|$)`).test(sessionFile),
  )
}

export default function TrustForkCheckIdentity(pi) {
  let rosterLogged = false
  let childIdentityPassed = null
  audit("plugin_initialized", { manifest_schema_version: MANIFEST.schema_version })

  pi.on("before_provider_request", (event) => {
    const payload = attestAgentTool(event.payload)
    if (!payload) return
    if (!rosterLogged) {
      for (const actor of MANIFEST.actors) {
        audit("identity_checked", {
          profile: actor.profile,
          slot: actor.slot,
          displayed_identity: actor.displayed_identity,
          verified_provider: actor.actual_identity.provider,
          verified_model: actor.actual_identity.api_model,
          display_matches_actual: displayMatchesActual(),
          identity_claim_status: MANIFEST.identity_claim_status,
        })
      }
      audit("roster_identity_attested", { checked_profiles: MANIFEST.actors.length })
      rosterLogged = true
    }
    return payload
  })

  pi.on("before_agent_start", (_event, ctx) => {
    const actor = profileFromSession(ctx)
    if (!actor) return
    const actualProvider = ctx.model?.provider ?? null
    const actualModel = ctx.model?.id ?? null
    const passed =
      actualProvider === actor.actual_identity.provider &&
      actualModel === actor.actual_identity.api_model
    childIdentityPassed = passed
    audit(passed ? "identity_runtime_verified" : "identity_check_failed", {
      session_id: ctx.sessionManager.getSessionId(),
      profile: actor.profile,
      slot: actor.slot,
      expected_provider: actor.actual_identity.provider,
      expected_model: actor.actual_identity.api_model,
      actual_provider: actualProvider,
      actual_model: actualModel,
      reason: passed ? null : "runtime_request_mismatch",
    })
  })

  pi.on("message_end", (event) => {
    if (childIdentityPassed !== false || event.message?.role !== "assistant") return
    const error = "TrustFork identity check rejected this child runtime model."
    return {
      message: {
        ...event.message,
        content: [{ type: "text", text: error }],
        stopReason: "error",
        errorMessage: error,
      },
    }
  })

  pi.on("tool_call", (event, ctx) => {
    if (childIdentityPassed === false) {
      audit("identity_check_failed", {
        session_id: ctx.sessionManager.getSessionId(),
        call_id: event.toolCallId,
        reason: "child_runtime_identity_unverified",
      })
      return {
        block: true,
        reason: "TrustFork identity check rejected this child runtime model.",
      }
    }
    if (event.toolName !== "Agent") return
    const profile = event.input?.subagent_type
    const actor = MANIFEST.actors.find((item) => item.profile === profile)
    if (!actor) {
      audit("identity_check_failed", {
        session_id: ctx.sessionManager.getSessionId(),
        call_id: event.toolCallId,
        profile: profile ?? null,
        reason: "unknown_profile",
      })
      return {
        block: true,
        reason: `TrustFork identity check rejected unverified profile: ${profile}`,
      }
    }
    audit("identity_check_passed", {
      session_id: ctx.sessionManager.getSessionId(),
      call_id: event.toolCallId,
      profile,
      slot: actor.slot,
      verified_provider: actor.actual_identity.provider,
      verified_model: actor.actual_identity.api_model,
    })
  })
}
