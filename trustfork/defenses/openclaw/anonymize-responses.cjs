const { appendFileSync, mkdirSync } = require("node:fs")

const MANIFEST = Object.freeze(__TRUSTFORK_DEFENSE_MANIFEST__)
const PLUGIN_ID = "trustfork-defense-anonymize-responses"
const LOG_DIR =
  process.env.TRUSTFORK_DEFENSE_LOG_DIR || "/logs/agent/openclaw/defense"
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

function redactRosterText(text) {
  let value = String(text ?? "")
  for (const actor of MANIFEST.actors) {
    const actual = actor.actual_identity
    const replacements = [
      `${actual.provider}/${actual.api_model}`,
      actor.displayed_identity,
      actual.display_model,
      actual.api_model,
      actual.provider,
      actual.family,
      `${actual.tier} model`,
      `${actual.tier} tier`,
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

function redactValue(value) {
  if (typeof value === "string") return redactRosterText(value)
  if (Array.isArray(value)) return value.map(redactValue)
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, redactValue(child)]),
    )
  }
  return value
}

function redactMessage(event, ctx, hook) {
  if (String(ctx.agentId || event.agentId || "") !== "main") return
  const message = event.message
  if (!message || typeof message !== "object") return
  const next = { ...message, content: redactValue(message.content) }
  if (JSON.stringify(next.content) === JSON.stringify(message.content)) return
  audit("response_anonymized", {
    hook,
    session_id: ctx.sessionId || null,
    session_key: ctx.sessionKey || event.sessionKey || null,
    tool: event.toolName || null,
    call_id: event.toolCallId || null,
  })
  return { message: next }
}

module.exports = {
  id: PLUGIN_ID,
  name: "TrustFork Anonymize Responses",
  register(api) {
    audit("plugin_initialized", {
      manifest_schema_version: MANIFEST.schema_version,
    })

    const entries = Array.isArray(api.config?.agents?.list)
      ? api.config.agents.list
      : []
    const missing = []
    for (const actor of MANIFEST.actors) {
      const profile = entries.find((entry) => entry?.id === actor.profile)
      const neutral = `Subagent ${actor.slot}`
      if (
        !profile ||
        profile.name !== neutral ||
        profile.description !== `${neutral}.`
      ) {
        missing.push(actor.profile)
      }
    }
    if (missing.length) {
      audit("anonymization_failed", { missing_profiles: missing })
      throw new Error(
        `TrustFork anonymization found a non-neutral roster: ${missing.join(", ")}`,
      )
    }
    audit("roster_anonymized", { changed_profiles: MANIFEST.actors.length })

    api.on("tool_result_persist", (event, ctx) =>
      redactMessage(event, ctx, "tool_result_persist"),
    )
    api.on("before_message_write", (event, ctx) =>
      redactMessage(event, ctx, "before_message_write"),
    )
  },
}
