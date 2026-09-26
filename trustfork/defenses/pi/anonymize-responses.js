import { appendFileSync, mkdirSync } from "node:fs"

const MANIFEST = Object.freeze(__TRUSTFORK_DEFENSE_MANIFEST__)
const LOG_DIR = process.env.TRUSTFORK_DEFENSE_LOG_DIR || "/logs/agent/pi/defense"
const LOG_PATH = `${LOG_DIR}/events.jsonl`
const DELEGATION_RESULT_TOOLS = new Set(["Agent", "get_subagent_result"])

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

function replacementsFor(actor) {
  const actual = actor.actual_identity
  return [
    [actor.displayed_identity, `Subagent ${actor.slot}`],
    [`${actual.provider}/${actual.api_model}`, "[identity redacted]"],
    [actual.display_model, "[identity redacted]"],
    [actual.api_model, "[identity redacted]"],
    [actual.provider, "[identity redacted]"],
    [actual.family, "[identity redacted]"],
    [`${actual.tier} model`, "[identity redacted]"],
    [`${actual.tier} tier`, "[identity redacted]"],
  ]
}

function redactText(text) {
  let value = String(text ?? "")
  for (const actor of MANIFEST.actors) {
    const replacements = replacementsFor(actor)
      .filter(([from]) => from)
      .sort(([left], [right]) => right.length - left.length)
    for (const [from, to] of replacements) {
      value = value.replace(new RegExp(escapeRegExp(from), "gi"), to)
    }
  }
  return value
}

function redactValue(value) {
  if (typeof value === "string") return redactText(value)
  if (Array.isArray(value)) return value.map(redactValue)
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, redactValue(item)]),
    )
  }
  return value
}

function toolName(tool) {
  return tool?.name ?? tool?.function?.name ?? null
}

function redactAgentTool(payload) {
  if (!payload || typeof payload !== "object" || !Array.isArray(payload.tools)) {
    return null
  }
  let found = false
  const tools = payload.tools.map((tool) => {
    if (toolName(tool) !== "Agent") return tool
    found = true
    return redactValue(tool)
  })
  return found ? { ...payload, tools } : null
}

export default function TrustForkAnonymizeResponses(pi) {
  let rosterLogged = false
  audit("plugin_initialized", { manifest_schema_version: MANIFEST.schema_version })

  pi.on("before_provider_request", (event) => {
    const payload = redactAgentTool(event.payload)
    if (!payload) return
    if (!rosterLogged) {
      audit("roster_anonymized", { changed_profiles: MANIFEST.actors.length })
      audit("task_definition_anonymized")
      rosterLogged = true
    }
    return payload
  })

  pi.on("tool_result", (event, ctx) => {
    if (!DELEGATION_RESULT_TOOLS.has(event.toolName)) return
    const content = event.content.map((item) =>
      item?.type === "text" ? { ...item, text: redactText(item.text) } : item,
    )
    const profile = event.input?.subagent_type ?? null
    const actor = MANIFEST.actors.find((item) => item.profile === profile)
    audit("response_anonymized", {
      session_id: ctx.sessionManager.getSessionId(),
      call_id: event.toolCallId,
      anonymous_slot: actor?.slot ?? null,
    })
    return { content }
  })
}
