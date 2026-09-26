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

function neutralDescription(actor) {
  return `Subagent ${actor.slot}.`
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

function redactRosterText(text) {
  let value = String(text ?? "")
  for (const actor of MANIFEST.actors) {
    const replacements = [
      `${actor.actual_identity.provider}/${actor.actual_identity.api_model}`,
      actor.displayed_identity,
      actor.actual_identity.display_model,
      actor.actual_identity.api_model,
      actor.actual_identity.provider,
      actor.actual_identity.family,
      `${actor.actual_identity.tier} model`,
      `${actor.actual_identity.tier} tier`,
    ]
      .filter(Boolean)
      .sort((left, right) => right.length - left.length)
    for (const replacement of replacements) {
      value = value.replace(
        new RegExp(escapeRegExp(replacement), "gi"),
        "[identity redacted]",
      )
    }
  }
  return value
}

export default async function TrustForkAnonymizeResponses() {
  audit("plugin_initialized", { manifest_schema_version: MANIFEST.schema_version })
  return {
    config: async (config) => {
      let changed = 0
      const missing = []
      for (const actor of MANIFEST.actors) {
        const profile = config.agent?.[actor.profile]
        if (!profile) {
          missing.push(actor.profile)
          continue
        }
        profile.description = neutralDescription(actor)
        changed += 1
      }
      if (missing.length) {
        audit("anonymization_failed", { missing_profiles: missing })
        throw new Error(
          `TrustFork anonymization could not find profiles: ${missing.join(", ")}`,
        )
      }
      audit("roster_anonymized", { changed_profiles: changed })
    },
    "tool.definition": async (input, output) => {
      if (input.toolID !== "task") return
      output.description = redactRosterText(output.description)
      audit("task_definition_anonymized")
    },
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "task") return
      const profile = input.args?.subagent_type ?? null
      const actor = MANIFEST.actors.find((item) => item.profile === profile)
      output.title = redactRosterText(output.title)
      output.output = redactRosterText(output.output)
      audit("response_anonymized", {
        session_id: input.sessionID,
        call_id: input.callID,
        anonymous_slot: actor?.slot ?? null,
      })
    },
  }
}
