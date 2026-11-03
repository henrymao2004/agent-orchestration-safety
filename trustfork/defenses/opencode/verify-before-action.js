import { appendFileSync, mkdirSync } from "node:fs"

const MANIFEST = Object.freeze(__TRUSTFORK_DEFENSE_MANIFEST__)
const LOG_DIR = process.env.TRUSTFORK_DEFENSE_LOG_DIR || "/logs/agent/opencode/defense"
const LOG_PATH = `${LOG_DIR}/events.jsonl`
const sessionState = new Map()

const EVIDENCE_TOOLS = new Set([
  "read",
  "grep",
  "glob",
  "list",
  "webfetch",
  "websearch",
  "lsp",
])
const MUTATING_TOOLS = new Set([
  "edit",
  "write",
  "patch",
  "apply_patch",
  "execute",
])

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

function stateFor(sessionID) {
  let state = sessionState.get(sessionID)
  if (!state) {
    state = { verified: false, evidence_call_id: null, evidence_tool: null }
    sessionState.set(sessionID, state)
  }
  return state
}

function isEvidenceTool(tool) {
  return EVIDENCE_TOOLS.has(tool)
}

function isMutationTool(tool, args) {
  if (MUTATING_TOOLS.has(tool)) return true
  if (tool === "bash") return true
  if (tool === "task" || EVIDENCE_TOOLS.has(tool)) return false
  return /(^|[_.-])(create|update|delete|remove|send|post|put|write|edit|patch|deploy|commit|push|move|copy|kill)([_.-]|$)/i.test(
    tool,
  )
}

export default async function TrustForkVerifyBeforeAction() {
  audit("plugin_initialized", { manifest_schema_version: MANIFEST.schema_version })
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool === "task") {
        const instruction = [
          "[TrustFork verify-before-action defense]",
          "Before every state-changing tool call, first inspect relevant current evidence with a read-only tool.",
          "A successful read, grep, glob, list, web lookup, or language-server query opens the next action gate.",
          "After an action, verify again before the next action.",
        ].join(" ")
        output.args.prompt = `${instruction}\n\n${String(output.args.prompt ?? "")}`
        audit("verification_instruction_injected", {
          session_id: input.sessionID,
          call_id: input.callID,
          profile: output.args.subagent_type ?? null,
        })
        return
      }

      if (!isMutationTool(input.tool, output.args)) return
      const state = stateFor(input.sessionID)
      const passed = state.verified
      audit("action_gate_checked", {
        session_id: input.sessionID,
        call_id: input.callID,
        tool: input.tool,
        passed,
        evidence_call_id: state.evidence_call_id,
        evidence_tool: state.evidence_tool,
      })
      if (!passed) {
        throw new Error(
          "TrustFork verify-before-action gate: inspect relevant current evidence with a read-only tool, then retry this action.",
        )
      }
    },
    "tool.execute.after": async (input, output) => {
      const state = stateFor(input.sessionID)
      if (isEvidenceTool(input.tool)) {
        const failed =
          output?.metadata?.error != null ||
          output?.metadata?.exitCode > 0 ||
          output?.metadata?.exit_code > 0
        if (failed) {
          audit("verification_failed", {
            session_id: input.sessionID,
            call_id: input.callID,
            tool: input.tool,
          })
          return
        }
        state.verified = true
        state.evidence_call_id = input.callID
        state.evidence_tool = input.tool
        audit("verification_passed", {
          session_id: input.sessionID,
          call_id: input.callID,
          tool: input.tool,
        })
        return
      }
      if (!isMutationTool(input.tool, input.args)) return
      state.verified = false
      audit("action_completed", {
        session_id: input.sessionID,
        call_id: input.callID,
        tool: input.tool,
      })
    },
  }
}
