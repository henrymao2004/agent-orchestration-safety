import { appendFileSync, mkdirSync } from "node:fs"

const MANIFEST = Object.freeze(__TRUSTFORK_DEFENSE_MANIFEST__)
const LOG_DIR = process.env.TRUSTFORK_DEFENSE_LOG_DIR || "/logs/agent/opencode/defense"
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

function displayMatchesActual(actor) {
  if (MANIFEST.identity_display_id === "M0") return null
  return ["M1", "M3", "M5"].includes(MANIFEST.identity_display_id)
}

export default async function TrustForkCheckIdentity() {
  const verifiedProfiles = new Set()
  audit("plugin_initialized", { manifest_schema_version: MANIFEST.schema_version })
  return {
    config: async (config) => {
      let checked = 0
      const failures = []
      for (const actor of MANIFEST.actors) {
        const profile = config.agent?.[actor.profile]
        if (!profile) {
          failures.push(`${actor.profile}:missing`)
          audit("identity_check_failed", {
            profile: actor.profile,
            slot: actor.slot,
            reason: "missing_profile",
          })
          continue
        }
        const expectedModel = `${actor.actual_identity.provider}/${actor.actual_identity.api_model}`
        if (profile.model !== expectedModel) {
          profile.description = `Subagent ${actor.slot}; identity verification failed.`
          failures.push(`${actor.profile}:runtime_model_mismatch`)
          audit("identity_check_failed", {
            profile: actor.profile,
            slot: actor.slot,
            reason: "runtime_model_mismatch",
            configured_model: profile.model ?? null,
            expected_model: expectedModel,
          })
          continue
        }
        profile.description = `${attestation(actor)}.`
        verifiedProfiles.add(actor.profile)
        audit("identity_checked", {
          profile: actor.profile,
          slot: actor.slot,
          displayed_identity: actor.displayed_identity,
          verified_provider: actor.actual_identity.provider,
          verified_model: actor.actual_identity.api_model,
          display_matches_actual: displayMatchesActual(actor),
          identity_claim_status: MANIFEST.identity_claim_status,
        })
        checked += 1
      }
      if (failures.length) {
        throw new Error(
          `TrustFork identity check rejected roster: ${failures.join(", ")}`,
        )
      }
      audit("roster_identity_attested", { checked_profiles: checked })
    },
    "chat.params": async (input) => {
      const actor = MANIFEST.actors.find((item) => item.profile === input.agent)
      if (!actor) return
      const expectedProvider = actor.actual_identity.provider
      const expectedModel = actor.actual_identity.api_model
      const actualProvider = input.model?.providerID ?? input.provider?.info?.id ?? null
      const actualModel = input.model?.id ?? null
      const passed =
        actualProvider === expectedProvider && actualModel === expectedModel
      audit(passed ? "identity_runtime_verified" : "identity_check_failed", {
        session_id: input.sessionID,
        profile: input.agent,
        slot: actor.slot,
        expected_provider: expectedProvider,
        expected_model: expectedModel,
        actual_provider: actualProvider,
        actual_model: actualModel,
        reason: passed ? null : "runtime_request_mismatch",
      })
      if (!passed) {
        throw new Error(
          `TrustFork identity check rejected runtime model ${actualProvider}/${actualModel} for ${input.agent}`,
        )
      }
    },
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "task") return
      const profile = output.args?.subagent_type
      const actor = MANIFEST.actors.find((item) => item.profile === profile)
      if (!actor || !verifiedProfiles.has(profile)) {
        audit("identity_check_failed", {
          session_id: input.sessionID,
          call_id: input.callID,
          profile: profile ?? null,
          reason: actor ? "unverified_runtime_model" : "unknown_profile",
        })
        throw new Error(`TrustFork identity check rejected unverified profile: ${profile}`)
      }
      audit("identity_check_passed", {
        session_id: input.sessionID,
        call_id: input.callID,
        profile,
        slot: actor.slot,
        verified_provider: actor.actual_identity.provider,
        verified_model: actor.actual_identity.api_model,
      })
    },
  }
}
