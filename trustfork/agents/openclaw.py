
import asyncio
import base64
import copy
import inspect
import json
import shlex
from pathlib import Path
from typing import Any, override

from harbor.agents.installed.base import (
    BaseInstalledAgent,
    CliFlag,
    with_prompt_template,
)
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.agent.name import AgentName
from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from harbor.utils.env import parse_bool_env_value
from harbor.utils.trajectory_utils import format_trajectory_json

OPENCLAW_AGENT_SETUP_TIMEOUT_SEC = 1200.0


def openclaw_session_jsonl_to_atif_steps(
    path: Path | str,
    *,
    instruction: str,
    model_name: str,
) -> list[Step] | None:
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    def _text_from_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        return "".join(
            p["text"]
            for p in content
            if isinstance(p, dict)
            and p.get("type") == "text"
            and isinstance(p.get("text"), str)
        )

    def _assistant_parts(content: Any) -> tuple[str, list[ToolCall]]:
        if not isinstance(content, list):
            return "", []
        texts: list[str] = []
        tools: list[ToolCall] = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "text" and isinstance(p.get("text"), str):
                texts.append(p["text"])
            elif p.get("type") == "toolCall" and isinstance(p.get("name"), str):
                raw = p.get("arguments", "")
                if isinstance(raw, str):
                    try:
                        args: dict[str, Any] = json.loads(raw) if raw.strip() else {}
                    except json.JSONDecodeError:
                        args = {"raw": raw}
                elif isinstance(raw, dict):
                    args = raw
                else:
                    args = {}
                cid = p.get("id")
                tools.append(
                    ToolCall(
                        tool_call_id=str(cid) if cid is not None else "",
                        function_name=p["name"],
                        arguments=args,
                    )
                )
        return "".join(texts), tools

    def _usage_metrics(usage: Any) -> Metrics | None:
        if not isinstance(usage, dict):
            return None
        inp = int(usage.get("input") or 0)
        out = int(usage.get("output") or 0)
        cr = int(usage.get("cacheRead") or 0)
        cw = int(usage.get("cacheWrite") or 0)
        if not (inp or out or cr):
            return None
        return Metrics(
            prompt_tokens=inp + cr or None,
            completion_tokens=out or None,
            cached_tokens=cr or None,
            extra=({"cache_write_tokens": cw} if cw else None),
        )

    rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "message":
            continue
        inner = rec.get("message")
        if not isinstance(inner, dict):
            continue
        role = inner.get("role")
        if role in ("user", "assistant", "toolResult"):
            rows.append((rec, inner))

    if not rows:
        return None

    steps: list[Step] = []
    sid = 0
    first_user = True
    i = 0
    while i < len(rows):
        rec, msg = rows[i]
        ts = rec.get("timestamp") if isinstance(rec.get("timestamp"), str) else None
        role = msg.get("role")

        if role == "user":
            body = _text_from_content(msg.get("content"))
            user_msg = (
                instruction.strip() if (first_user and instruction.strip()) else body
            )
            first_user = False
            sid += 1
            steps.append(
                Step(
                    step_id=sid,
                    source="user",
                    message=user_msg or "(empty user message)",
                    timestamp=ts,
                )
            )
            i += 1
            continue

        if role == "assistant":
            text, tools = _assistant_parts(msg.get("content"))
            err = msg.get("errorMessage")
            if text.strip():
                agent_msg = text.strip()
            elif isinstance(err, str) and err.strip():
                agent_msg = f"(error) {err.strip()}"
            else:
                agent_msg = "(no assistant text)"

            j = i + 1
            pending = {t.tool_call_id for t in tools if t.tool_call_id}
            ob: list[ObservationResult] = []
            while j < len(rows) and rows[j][1].get("role") == "toolResult":
                tr = rows[j][1]
                cid = str(tr.get("toolCallId") or "")
                if cid not in pending:
                    break
                details = tr.get("details")
                body_t = ""
                if isinstance(details, dict):
                    agg = details.get("aggregated")
                    if isinstance(agg, str) and agg.strip():
                        body_t = agg
                if not body_t:
                    body_t = _text_from_content(tr.get("content"))
                ob.append(
                    ObservationResult(
                        source_call_id=cid or None, content=body_t or None
                    )
                )
                pending.discard(cid)
                j += 1
                if not pending:
                    break

            sid += 1
            steps.append(
                Step(
                    step_id=sid,
                    source="agent",
                    message=agent_msg,
                    timestamp=ts,
                    model_name=model_name,
                    tool_calls=tools or None,
                    observation=Observation(results=ob) if ob else None,
                    metrics=_usage_metrics(msg.get("usage")),
                )
            )
            i = j
            continue

        i += 1

    if len(steps) < 2:
        return None
    return steps


def openclaw_bundle_to_atif_steps(
    bundle_dir: Path | str,
    *,
    instruction: str,
    model_name: str,
) -> list[Step] | None:
    bundle_dir = Path(bundle_dir)
    branch_path = bundle_dir / "session-branch.json"
    try:
        payload = json.loads(branch_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    def find_rows(value: Any) -> list[Any] | None:
        if isinstance(value, list):
            if any(
                isinstance(row, dict)
                and (row.get("type") == "message" or "role" in row)
                for row in value
            ):
                return value
            for child in value:
                found = find_rows(child)
                if found:
                    return found
        elif isinstance(value, dict):
            for key in ("entries", "messages", "branch", "transcript"):
                if key in value:
                    found = find_rows(value[key])
                    if found:
                        return found
            for child in value.values():
                found = find_rows(child)
                if found:
                    return found
        return None

    rows = find_rows(payload)
    if not rows:
        return None
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("type") == "message" and isinstance(row.get("message"), dict):
            normalized.append(row)
        elif isinstance(row.get("role"), str):
            normalized.append({"type": "message", "message": row})
    if not normalized:
        return None
    normalized_path = bundle_dir / "harbor-session-branch.jsonl"
    normalized_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in normalized) + "\n",
        encoding="utf-8",
    )
    return openclaw_session_jsonl_to_atif_steps(
        normalized_path,
        instruction=instruction,
        model_name=model_name,
    )


def _openclaw_decode_last_json_dict_suffix(raw: str):
    text = raw.strip()
    if not text:
        return None
    dec = json.JSONDecoder()
    for start in range(len(text) - 1, -1, -1):
        if text[start] != "{":
            continue
        try:
            obj, consumed = dec.raw_decode(text[start:])
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        if text[start + consumed :].strip():
            continue
        return obj
    return None


def _openclaw_container_copy_session_transcript() -> None:
    import json
    import shutil
    import sys
    from pathlib import Path

    log_path = Path("/logs/agent/openclaw.txt")
    if not log_path.is_file():
        sys.exit(0)
    raw = log_path.read_text(encoding="utf-8", errors="replace")
    text = raw.strip()
    if not text:
        sys.exit(0)
    dec = json.JSONDecoder()
    envelope = None
    for start in range(len(text) - 1, -1, -1):
        if text[start] != "{":
            continue
        try:
            obj, consumed = dec.raw_decode(text[start:])
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        if text[start + consumed :].strip():
            continue
        envelope = obj
        break
    if not envelope:
        sys.exit(0)
    meta = envelope.get("meta")
    if not isinstance(meta, dict):
        sys.exit(0)
    agent_meta = meta.get("agentMeta")
    if not isinstance(agent_meta, dict):
        sys.exit(0)
    session_file = agent_meta.get("sessionFile")
    if not isinstance(session_file, str) or not session_file.strip():
        sys.exit(0)
    src = Path(session_file)
    if not src.is_file():
        sys.exit(0)
    dst = Path("/logs/agent") / "openclaw.session.jsonl"
    shutil.copy2(src, dst)


_OPENCLAW_NODE_VERSION = "24.15.0"
_OPENCLAW_BATCH_WAKE_DIR = (
    Path(__file__).resolve().parents[1] / "base-image" / "openclaw-batch-wake"
)


def _nvm_openclaw(cmd: str) -> str:
    return f". ~/.nvm/nvm.sh && nvm use {_OPENCLAW_NODE_VERSION} >/dev/null && {cmd}"


class OpenClaw(BaseInstalledAgent):

    SUPPORTS_ATIF: bool = True
    SUPPORTS_RESUME: bool = True

    _UPLOAD_CONFIG_FILENAME = "openclaw.upload.json"
    _CONTAINER_LOGS_AGENT = "/logs/agent"
    _TRUSTFORK_PLUGIN_ID = "trustfork-profile-overlay"
    _TRUSTFORK_PLUGIN_DIR = "/tmp/trustfork-openclaw-profile-overlay"
    _TRUSTFORK_DEFENSE_PLUGIN_ID_PREFIX = "trustfork-defense-"
    _TRUSTFORK_DEFENSE_PLUGIN_DIR = "/tmp/trustfork-openclaw-defense"
    _TRUSTFORK_DEFENSE_NAMES = frozenset(
        {"anonymize-responses", "check-identity", "verify-before-action"}
    )
    _HARBOR_PARENT_SESSION_KEY_PREFIX = "harbor"
    _OPENCLAW_BATCH_WAKE_REMOTE_DIR = "/tmp/trustfork-openclaw-batch-wake"
    _OPENCLAW_BATCH_WAKE_FILES = (
        "apply.mjs",
        "subagent-announce.requester-settle-wake.js",
    )

    _SETUP_BASELINE: dict[str, Any] = {
        "agents": {"defaults": {"workspace": "."}},
        "gateway": {"mode": "local"},
    }
    _SETUP_CLI = "openclaw setup --baseline --workspace ."

    CLI_FLAGS = [
        CliFlag("openclaw_agent_id", cli="--agent", type="str", default="main"),
        CliFlag("timeout", cli="--timeout", type="int"),
    ]

    _DEFAULT_CONFIG: dict[str, Any] = {}

    _HEADLESS_TOOL_DENY: tuple[str, ...] = ("message",)

    _SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"anthropic", "nvidia", "openai"})

    @classmethod
    def _provider_env_keys(cls, provider: str) -> tuple[str, ...]:
        prefix = cls._provider_env_prefix(provider)
        return (f"{prefix}_API_KEY", f"{prefix}_BASE_URL")

    def _validate_provider(self, provider: str) -> None:
        configured: set[str] = set()
        models = self._openclaw_config.get("models")
        if isinstance(models, dict):
            providers = models.get("providers")
            if isinstance(providers, dict):
                configured = {str(key) for key in providers}
        if provider not in self._SUPPORTED_PROVIDERS and provider not in configured:
            raise ValueError(
                f"Unsupported provider {provider!r}. Supported providers: "
                f"{sorted(self._SUPPORTED_PROVIDERS)}. Configure the provider "
                "under models.providers or subclass OpenClaw and extend "
                "`_SUPPORTED_PROVIDERS` to add more."
            )

    def __init__(
        self,
        *args,
        openclaw_config: dict[str, Any] | None = None,
        openclaw_trustfork_roster: list[dict[str, Any]] | None = None,
        openclaw_trustfork_defense: dict[str, Any] | None = None,
        reuse_preinstalled: bool = False,
        **kwargs,
    ):
        override_setup_timeout_sec = kwargs.pop("override_setup_timeout_sec", None)
        self._use_openclaw_session_jsonl_for_steps = bool(
            kwargs.pop("session_to_trajectory", True)
        )
        raw_fr = kwargs.pop("failover_retries", None)
        self._failover_retries: int | None = None
        if raw_fr is not None:
            self._failover_retries = int(raw_fr)
            if self._failover_retries < 0:
                raise ValueError("failover_retries must be non-negative")
        self._install_exec_timeout_sec = int(
            override_setup_timeout_sec or OPENCLAW_AGENT_SETUP_TIMEOUT_SEC
        )
        super().__init__(*args, **kwargs)
        self._openclaw_config: dict[str, Any] = openclaw_config or {}
        self._openclaw_trustfork_roster = openclaw_trustfork_roster
        self._openclaw_trustfork_defense = copy.deepcopy(openclaw_trustfork_defense)
        self._reuse_preinstalled = parse_bool_env_value(
            reuse_preinstalled,
            name="reuse_preinstalled",
            default=False,
        )
        self._openclaw_parent_session_index = 0
        self._openclaw_parent_session_key: str | None = None
        self._validate_trustfork_roster()
        self._validate_trustfork_defense()

    def _parent_session_key(self) -> str:
        if not self._resume or self._openclaw_parent_session_key is None:
            self._openclaw_parent_session_index += 1
            self._openclaw_parent_session_key = (
                f"{self._HARBOR_PARENT_SESSION_KEY_PREFIX}-"
                f"{self._openclaw_parent_session_index}"
            )
        return self._openclaw_parent_session_key

    def _validate_trustfork_roster(self) -> None:
        if self._openclaw_trustfork_roster is None:
            return
        expected = ["candidate_a", "candidate_b", "candidate_c", "candidate_d"]
        names = [str(row.get("name")) for row in self._openclaw_trustfork_roster]
        if names != expected:
            raise ValueError(
                "openclaw_trustfork_roster must contain candidate_a through "
                "candidate_d in fixed order"
            )
        for row in self._openclaw_trustfork_roster:
            for key in ("description", "model", "systemPrompt", "workspace"):
                if key not in row:
                    raise ValueError(
                        f"Incomplete OpenClaw child profile: {row['name']}"
                    )
            if not isinstance(row["systemPrompt"], str):
                raise ValueError(f"Invalid OpenClaw child system prompt: {row['name']}")

    def _validate_trustfork_defense(self) -> None:
        defense = self._openclaw_trustfork_defense
        if defense is None:
            return
        if self._openclaw_trustfork_roster is None:
            raise ValueError(
                "openclaw_trustfork_defense requires openclaw_trustfork_roster"
            )
        if not isinstance(defense, dict) or set(defense) != {
            "name",
            "manifest",
            "source",
        }:
            raise ValueError(
                "openclaw_trustfork_defense must contain exactly name, manifest, "
                "and source"
            )

        name = defense["name"]
        if not isinstance(name, str) or name not in self._TRUSTFORK_DEFENSE_NAMES:
            raise ValueError(f"Unsupported OpenClaw TrustFork defense: {name!r}")
        source = defense["source"]
        manifest = defense["manifest"]
        if not isinstance(source, str) or not source.strip():
            raise ValueError("OpenClaw TrustFork defense source must be non-empty")
        if not isinstance(manifest, dict):
            raise ValueError("OpenClaw TrustFork defense manifest must be an object")
        if manifest.get("schema_version") != "trustfork-defense-manifest-v1":
            raise ValueError("Invalid OpenClaw TrustFork defense manifest schema")
        if manifest.get("defense") != name:
            raise ValueError("OpenClaw TrustFork defense name/manifest mismatch")
        if not isinstance(manifest.get("system_id"), str) or not isinstance(
            manifest.get("task_id"), str
        ):
            raise ValueError(
                "OpenClaw TrustFork defense manifest requires system_id and task_id"
            )

        actors = manifest.get("actors")
        roster = self._openclaw_trustfork_roster
        if not isinstance(actors, list) or len(actors) != len(roster):
            raise ValueError(
                "OpenClaw TrustFork defense manifest must cover every roster profile"
            )
        for actor, profile in zip(actors, roster, strict=True):
            if not isinstance(actor, dict) or actor.get("profile") != profile["name"]:
                raise ValueError(
                    "OpenClaw TrustFork defense actor order must match the roster"
                )
            actual = actor.get("actual_identity")
            if not isinstance(actual, dict):
                raise ValueError(
                    f"Missing actual identity for OpenClaw profile {profile['name']}"
                )
            actual_ref = f"{actual.get('provider')}/{actual.get('api_model')}"
            if actual_ref != profile["model"]:
                raise ValueError(
                    f"OpenClaw TrustFork defense identity mismatch for {profile['name']}"
                )
            if name == "check-identity" and not all(
                isinstance(actual.get(key), str) and actual[key]
                for key in ("display_model", "family", "tier")
            ):
                raise ValueError(
                    "OpenClaw check-identity requires display_model, family, and "
                    f"tier for {profile['name']}"
                )

        if "__TRUSTFORK_DEFENSE_MANIFEST__" in source:
            raise ValueError("OpenClaw TrustFork defense source is not rendered")
        rendered_manifest = json.dumps(
            manifest, ensure_ascii=False, separators=(",", ":")
        )
        if rendered_manifest not in source:
            raise ValueError(
                "OpenClaw TrustFork defense source does not embed its manifest"
            )
        if json.dumps(self._trustfork_defense_plugin_id()) not in source:
            raise ValueError(
                "OpenClaw TrustFork defense source has the wrong plugin id"
            )

    def _trustfork_defense_plugin_id(self) -> str:
        defense = self._openclaw_trustfork_defense
        if defense is None:
            raise ValueError("No OpenClaw TrustFork defense is configured")
        return f"{self._TRUSTFORK_DEFENSE_PLUGIN_ID_PREFIX}{defense['name']}"

    def _trustfork_defense_plugin_path(self) -> str:
        return f"{self._TRUSTFORK_DEFENSE_PLUGIN_DIR}/index.cjs"

    def _trustfork_defense_hook_permissions(self) -> dict[str, bool]:
        defense = self._openclaw_trustfork_defense
        if defense is None or defense["name"] == "anonymize-responses":
            return {}
        if defense["name"] == "check-identity":
            return {"allowConversationAccess": True}
        return {
            "allowConversationAccess": True,
            "allowPromptInjection": True,
        }

    def _trustfork_profile_plugin_source(self) -> str:
        roster = {
            str(row["name"]): {"hiddenGoal": str(row["systemPrompt"])}
            for row in self._openclaw_trustfork_roster or []
        }
        roster_json = json.dumps(roster, ensure_ascii=False, separators=(",", ":"))
        return f"""const roster = Object.freeze({roster_json});
module.exports = {{
  id: {json.dumps(self._TRUSTFORK_PLUGIN_ID)},
  name: "TrustFork Profile Overlay",
  register(api) {{
    api.on("before_prompt_build", (_event, ctx) => {{
      const profile = roster[String(ctx.agentId || "")];
      if (!profile || !profile.hiddenGoal) return;
      return {{ appendSystemContext: profile.hiddenGoal }};
    }});
    api.on("before_tool_call", (event, ctx) => {{
      if (String(ctx.agentId || "") !== "main" || event.toolName !== "sessions_spawn") return;
      const params = {{ ...(event.params || {{}}) }};
      const profile = roster[String(params.agentId || "")];
      if (!profile) return;
      params.cwd = "/workspace";
      delete params.model;
      return {{ params }};
    }});
  }},
}};
"""

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                OpenClaw._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    @classmethod
    def _merge_harbor_headless_tool_denies(cls, cfg: dict[str, Any]) -> None:
        raw_tools = cfg.get("tools")
        if not isinstance(raw_tools, dict):
            cfg["tools"] = {"deny": list(cls._HEADLESS_TOOL_DENY)}
            return
        deny = raw_tools.get("deny")
        if deny is None:
            raw_tools["deny"] = list(cls._HEADLESS_TOOL_DENY)
            return
        if not isinstance(deny, list):
            raw_tools["deny"] = list(cls._HEADLESS_TOOL_DENY)
            return
        seen: set[str] = set()
        merged: list[str] = []
        for item in deny:
            if isinstance(item, str) and item not in seen:
                seen.add(item)
                merged.append(item)
        for name in cls._HEADLESS_TOOL_DENY:
            if name not in seen:
                seen.add(name)
                merged.append(name)
        raw_tools["deny"] = merged

    @staticmethod
    def _shell_copy_openclaw_session_to_logs() -> str:
        body = inspect.getsource(_openclaw_container_copy_session_transcript)
        script = body + "\n_openclaw_container_copy_session_transcript()\n"
        return "python3 -c " + shlex.quote(script)

    @classmethod
    def _shell_install_uploaded_config(cls) -> str:
        uploaded = f"{cls._CONTAINER_LOGS_AGENT}/{cls._UPLOAD_CONFIG_FILENAME}"
        script = f"""
import json
from pathlib import Path

target = Path.home() / ".openclaw" / "openclaw.json"
incoming = json.loads(Path({uploaded!r}).read_text(encoding="utf-8"))
baseline = json.loads(target.read_text(encoding="utf-8"))
baseline_meta = baseline.get("meta")
incoming_meta = incoming.get("meta")
if isinstance(baseline_meta, dict):
    merged_meta = dict(baseline_meta)
    if isinstance(incoming_meta, dict):
        merged_meta.update(incoming_meta)
    incoming["meta"] = merged_meta
target.write_text(json.dumps(incoming, indent=2) + "\\n", encoding="utf-8")
"""
        return "python3 -c " + shlex.quote(script)

    async def _copy_openclaw_session_file_to_agent_logs(
        self, environment: BaseEnvironment, env: dict[str, str]
    ) -> None:
        try:
            await self.exec_as_agent(
                environment,
                command=self._shell_copy_openclaw_session_to_logs(),
                env=env,
            )
        except Exception:
            self.logger.debug(
                "Could not copy OpenClaw session file to "
                f"{self._CONTAINER_LOGS_AGENT}/openclaw.session.jsonl (non-fatal)",
                exc_info=True,
            )

    async def _install_trustfork_profile_plugin(
        self, environment: BaseEnvironment, env: dict[str, str]
    ) -> None:
        if self._openclaw_trustfork_roster is None:
            return
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {shlex.quote(self._TRUSTFORK_PLUGIN_DIR)}",
            env=env,
        )
        await self._upload_config_text(
            environment,
            content=self._trustfork_profile_plugin_source(),
            remote_path=f"{self._TRUSTFORK_PLUGIN_DIR}/index.cjs",
            filename="trustfork-profile-overlay.cjs",
        )
        await self._upload_config_text(
            environment,
            content=json.dumps(
                {
                    "id": self._TRUSTFORK_PLUGIN_ID,
                    "name": "TrustFork Profile Overlay",
                    "configSchema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {},
                    },
                },
                indent=2,
            )
            + "\n",
            remote_path=f"{self._TRUSTFORK_PLUGIN_DIR}/openclaw.plugin.json",
            filename="trustfork-profile-overlay-manifest.json",
        )

    def _trustfork_sessions_spawn_schema_patch_command(self) -> str | None:
        if self._openclaw_trustfork_roster is None:
            return None
        candidate_ids = [str(row["name"]) for row in self._openclaw_trustfork_roster]
        literal_rows = ", ".join(
            f"Type.Literal({json.dumps(candidate_id)})"
            for candidate_id in candidate_ids
        )
        replacement = (
            "agentId: Type.Union(["
            + literal_rows
            + "], { description: \"Required TrustFork candidate profile.\" }),"
        )
        script = f"""
import json
from pathlib import Path

dist = (
    Path.home()
    / ".nvm/versions/node/v{_OPENCLAW_NODE_VERSION}/lib/node_modules/openclaw/dist"
)
start_marker = "function createSessionsSpawnToolSchema(params) {{"
end_marker = "function resolveAcpUnavailableMessage(opts) {{"
needle = "agentId: Type.Optional(Type.String()),"
replacement = {replacement!r}
patched = []
already = []
for path in sorted(dist.glob("openclaw-tools-*.js")):
    text = path.read_text(encoding="utf-8")
    start = text.find(start_marker)
    end = text.find(end_marker, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        continue
    segment = text[start:end]
    if replacement in segment:
        already.append(str(path))
        continue
    if segment.count(needle) != 1:
        raise RuntimeError(
            f"unexpected sessions_spawn agentId schema in {{path}}"
        )
    segment = segment.replace(needle, replacement, 1)
    path.write_text(text[:start] + segment + text[end:], encoding="utf-8")
    patched.append(str(path))
if not patched and not already:
    raise RuntimeError("OpenClaw sessions_spawn schema chunk not found")
Path("/logs/agent/trustfork-sessions-spawn-schema.json").write_text(
    json.dumps(
        {{
            "schema": "required-literal-union",
            "agentIds": {candidate_ids!r},
            "patched": patched,
            "alreadyPatched": already,
        }},
        indent=2,
    )
    + "\\n",
    encoding="utf-8",
)
"""
        payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
        return f"printf %s {shlex.quote(payload)} | base64 -d | python3"

    async def _patch_trustfork_sessions_spawn_schema(
        self, environment: BaseEnvironment, env: dict[str, str]
    ) -> None:
        command = self._trustfork_sessions_spawn_schema_patch_command()
        if command is None:
            return
        await self.exec_as_agent(environment, command=command, env=env)

    async def _apply_openclaw_batch_wake_backport(
        self, environment: BaseEnvironment, env: dict[str, str]
    ) -> None:
        """Ensure the pinned OpenClaw build carries the batch wake-up patch.

        The script is idempotent, so on prepatched images it only verifies the marker.
        """
        if self._openclaw_trustfork_roster is None:
            return
        remote_dir = self._OPENCLAW_BATCH_WAKE_REMOTE_DIR
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {shlex.quote(remote_dir)}",
            env=env,
        )
        for filename in self._OPENCLAW_BATCH_WAKE_FILES:
            await self._upload_config_text(
                environment,
                content=(_OPENCLAW_BATCH_WAKE_DIR / filename).read_text(
                    encoding="utf-8"
                ),
                remote_path=f"{remote_dir}/{filename}",
                filename=f"openclaw-batch-wake-{filename}",
            )
        await self.exec_as_agent(
            environment,
            command=_nvm_openclaw(
                f"node {shlex.quote(remote_dir + '/apply.mjs')} "
                '"$(npm root -g)/openclaw" '
                "> /logs/agent/trustfork-openclaw-batch-wake.json"
            ),
            env=env,
        )

    async def _install_trustfork_defense_plugin(
        self, environment: BaseEnvironment, env: dict[str, str]
    ) -> None:
        defense = self._openclaw_trustfork_defense
        if defense is None:
            return
        plugin_id = self._trustfork_defense_plugin_id()
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {shlex.quote(self._TRUSTFORK_DEFENSE_PLUGIN_DIR)}",
            env=env,
        )
        await self._upload_config_text(
            environment,
            content=defense["source"],
            remote_path=self._trustfork_defense_plugin_path(),
            filename=f"{plugin_id}.cjs",
        )
        await self._upload_config_text(
            environment,
            content=json.dumps(
                {
                    "id": plugin_id,
                    "name": f"TrustFork {defense['name']} defense",
                    "configSchema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {},
                    },
                },
                indent=2,
            )
            + "\n",
            remote_path=(f"{self._TRUSTFORK_DEFENSE_PLUGIN_DIR}/openclaw.plugin.json"),
            filename=f"{plugin_id}-manifest.json",
        )

    async def _export_native_trajectories(
        self, environment: BaseEnvironment, env: dict[str, str]
    ) -> None:
        script = r"""
import json
import pathlib
import re
import shutil
import subprocess

logs = pathlib.Path("/logs/agent/openclaw-native")
logs.mkdir(parents=True, exist_ok=True)
# ``sessions --all-agents`` can omit short-lived completion sessions, so copy
# the raw transcripts first.
state_root = pathlib.Path.home() / ".openclaw" / "agents"
raw_root = logs / "raw-state"
if state_root.is_dir():
    for source in state_root.glob("*/sessions"):
        destination = raw_root / source.parent.name / "sessions"
        destination.mkdir(parents=True, exist_ok=True)
        for path in source.glob("*.jsonl"):
            shutil.copy2(path, destination / path.name)
        store = source / "sessions.json"
        if store.is_file():
            shutil.copy2(store, destination / store.name)
listing = subprocess.run(
    ["openclaw", "sessions", "--all-agents", "--limit", "all", "--json"],
    check=False,
    capture_output=True,
    text=True,
)
(logs / "sessions.json").write_text(listing.stdout or "[]\n")
(logs / "sessions.stderr.txt").write_text(listing.stderr or "")
try:
    payload = json.loads(listing.stdout)
except json.JSONDecodeError:
    payload = []
rows = payload.get("sessions", payload) if isinstance(payload, dict) else payload
if not isinstance(rows, list):
    rows = []
workspace = pathlib.Path("/tmp/openclaw-trustfork-export")
workspace.mkdir(parents=True, exist_ok=True)
for index, row in enumerate(rows):
    if not isinstance(row, dict):
        continue
    key = row.get("key") or row.get("sessionKey")
    if not isinstance(key, str) or not key:
        continue
    label = re.sub(r"[^a-zA-Z0-9_-]+", "-", key).strip("-")[:80]
    output = f"{index:03d}-{label or 'session'}"
    result = subprocess.run(
        [
            "openclaw",
            "sessions",
            "export-trajectory",
            "--session-key",
            key,
            "--workspace",
            str(workspace),
            "--output",
            output,
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    (logs / f"{output}.export.json").write_text(result.stdout or "")
    if result.stderr:
        (logs / f"{output}.export.stderr.txt").write_text(result.stderr)
exports = workspace / ".openclaw" / "trajectory-exports"
if exports.is_dir():
    import shutil

    shutil.copytree(exports, logs / "trajectories", dirs_exist_ok=True)
"""
        try:
            await self.exec_as_agent(
                environment,
                command=_nvm_openclaw("python3 -c " + shlex.quote(script)),
                env=env,
            )
        except Exception:
            self.logger.debug(
                "Could not export OpenClaw native trajectories (non-fatal)",
                exc_info=True,
            )

    @staticmethod
    def _gateway_run_command() -> str:
        return _nvm_openclaw(
            "echo $$ > /logs/agent/openclaw-gateway.pid\n"
            "exec openclaw gateway run > /logs/agent/openclaw-gateway.log 2>&1"
        )

    @staticmethod
    def _gateway_readiness_command() -> str:
        return (
            "for attempt in $(seq 1 180); do\n"
            "  if curl -fsS http://127.0.0.1:18789/readyz >/dev/null 2>&1; then\n"
            "    exit 0\n"
            "  fi\n"
            "  sleep 1\n"
            "done\n"
            "cat /logs/agent/openclaw-gateway.log >&2\n"
            "exit 1"
        )

    async def _start_gateway(
        self, environment: BaseEnvironment, env: dict[str, str]
    ) -> asyncio.Task[Any]:
        gateway_task = asyncio.create_task(
            self.exec_as_agent(
                environment,
                command=self._gateway_run_command(),
                env=env,
            )
        )
        readiness_task = asyncio.create_task(
            self.exec_as_agent(
                environment,
                command=self._gateway_readiness_command(),
                env=env,
            )
        )
        done, _ = await asyncio.wait(
            {gateway_task, readiness_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if gateway_task in done:
            readiness_task.cancel()
            try:
                await readiness_task
            except asyncio.CancelledError:
                pass
            await gateway_task
            raise RuntimeError("OpenClaw Gateway exited before reporting ready")
        try:
            await readiness_task
        except BaseException:
            await self._stop_gateway(environment, env, gateway_task)
            raise
        return gateway_task

    async def _stop_gateway(
        self,
        environment: BaseEnvironment,
        env: dict[str, str],
        gateway_task: asyncio.Task[Any],
    ) -> None:
        try:
            await self.exec_as_agent(
                environment,
                command=self._stop_gateway_command(),
                env=env,
            )
        except Exception:
            self.logger.debug("Could not stop trial-local OpenClaw Gateway")
        try:
            await asyncio.wait_for(asyncio.shield(gateway_task), timeout=10)
        except Exception:
            if not gateway_task.done():
                gateway_task.cancel()
                try:
                    await gateway_task
                except asyncio.CancelledError:
                    pass
            self.logger.debug(
                "Trial-local OpenClaw Gateway stopped with a non-zero status",
                exc_info=True,
            )

    @staticmethod
    def _wait_for_native_orchestration_command() -> str:
        script = r"""
import json
import pathlib
import sys
import time
from datetime import datetime

# Observation-only wait: child-result delivery happens inside the OpenClaw
# gateway. The deadline keeps the run inside Harbor's agent timeout.
deadline = time.monotonic() + 1140
logs = pathlib.Path("/logs/agent")
state_root = pathlib.Path.home() / ".openclaw" / "agents"
stable_polls = 0

def rows(path):
    parsed = []
    try:
        for raw in path.read_text(errors="replace").splitlines():
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                parsed.append(value)
    except OSError:
        pass
    return parsed

def millis(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            return 0
    return 0

def event_time(row):
    message = row.get("message")
    if isinstance(message, dict):
        value = message.get("timestamp")
        if value is not None:
            return millis(value)
    return millis(row.get("timestamp") or row.get("ts"))

def is_settled(message):
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return True
    return not any(
        isinstance(item, dict) and item.get("type") == "toolCall"
        for item in content
    )

def messages(parsed):
    return [
        (event_time(row), row["message"])
        for row in parsed
        if row.get("type") == "message" and isinstance(row.get("message"), dict)
    ]

def accepted_children(parsed):
    accepted = {}
    for _timestamp, message in messages(parsed):
        if message.get("role") != "toolResult" or message.get("toolName") != "sessions_spawn":
            continue
        details = message.get("details")
        if not isinstance(details, dict) or details.get("status") != "accepted":
            continue
        key = details.get("childSessionKey")
        if isinstance(key, str) and key:
            accepted[key] = _timestamp
    return accepted

def session_path(key):
    parts = key.split(":")
    if len(parts) < 4 or parts[0] != "agent":
        return None
    session_dir = state_root / parts[1] / "sessions"
    # ``childSessionKey`` is a routing key; sessions.json maps it to the
    # transcript's sessionId.
    try:
        index = json.loads((session_dir / "sessions.json").read_text())
    except (OSError, json.JSONDecodeError):
        index = {}
    entry = index.get(key) if isinstance(index, dict) else None
    if isinstance(entry, dict):
        session_id = entry.get("sessionId")
        if isinstance(session_id, str) and session_id:
            candidate = session_dir / (session_id + ".jsonl")
            if candidate.is_file():
                return candidate
    # Some builds use the key suffix as the session id.
    candidate = session_dir / (parts[-1] + ".jsonl")
    return candidate if candidate.is_file() else None

def lifecycle_flags(parsed):
    # The paused state appears either as direct fields or as a final
    # ``openclaw.sessions_yield`` custom entry, so inspect both.
    flags = {"livenessState": None, "yielded": False, "replayInvalid": False}
    for row in parsed:
        stack = [row]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                if "livenessState" in value:
                    flags["livenessState"] = value.get("livenessState")
                if "yielded" in value:
                    flags["yielded"] = value.get("yielded") is True
                if "replayInvalid" in value:
                    flags["replayInvalid"] = value.get("replayInvalid") is True
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    return flags

def snapshot():
    main_paths = sorted((state_root / "main" / "sessions").glob("*.jsonl"))
    main_paths = [path for path in main_paths if not path.name.endswith(".trajectory.jsonl")]
    if not main_paths:
        return {"complete": False, "reason": "root_missing", "children": []}
    # Completion delivery can create additional main-agent transcripts, so
    # treat all of them as ordered continuations of the root session named in
    # the initial CLI envelope.
    candidates = [(path, rows(path)) for path in main_paths]
    root_session_id = None
    try:
        raw_envelope = (logs / "openclaw.txt").read_text(errors="replace")
        decoder = json.JSONDecoder()
        for offset, char in enumerate(raw_envelope):
            if char != "{":
                continue
            try:
                envelope, _ = decoder.raw_decode(raw_envelope[offset:])
            except json.JSONDecodeError:
                continue
            result = envelope.get("result", envelope) if isinstance(envelope, dict) else {}
            meta = result.get("meta", {}) if isinstance(result, dict) else {}
            agent_meta = meta.get("agentMeta", {}) if isinstance(meta, dict) else {}
            value = agent_meta.get("sessionId") if isinstance(agent_meta, dict) else None
            if isinstance(value, str) and value:
                root_session_id = value
    except OSError:
        pass
    root_path = next(
        (path for path in main_paths if path.stem == root_session_id),
        None,
    )
    if root_path is None:
        return {
            "complete": False,
            "reason": "canonical_root_unresolved",
            "root_session_id": root_session_id,
            "children": [],
        }
    root_paths = [root_path] + sorted(
        (path for path in main_paths if path != root_path),
        key=lambda path: min(
            (event_time(row) for row in rows(path)),
            default=0,
        ),
    )
    root_rows = sorted(
        (row for path in root_paths for row in rows(path)),
        key=event_time,
    )
    root_messages = messages(root_rows)
    root_last_time, root_last = root_messages[-1] if root_messages else (0, None)
    accepted = accepted_children(root_rows)
    child_states = []
    child_terminal_times = []
    for key in accepted:
        path = session_path(key)
        parsed = rows(path) if path else []
        child_messages = messages(parsed)
        child_time, child_last = child_messages[-1] if child_messages else (0, None)
        child_flags = lifecycle_flags(parsed)
        child_ok = (
            path is not None
            and is_settled(child_last)
            and child_flags["livenessState"] != "paused"
            and not child_flags["yielded"]
            and not child_flags["replayInvalid"]
        )
        if child_ok:
            child_terminal_times.append(child_time)
        child_states.append(
            {
                "key": key,
                "path": str(path) if path else None,
                "terminal": child_ok,
                "last_time": child_time,
                **child_flags,
            }
        )
    last_yield_time = max(
        (
            event_time(row)
            for row in root_rows
            if row.get("type") in {"custom", "custom_message"}
            and row.get("customType") == "openclaw.sessions_yield"
        ),
        default=0,
    )
    root_flags = lifecycle_flags(root_rows)
    all_children_terminal = len(child_terminal_times) == len(accepted)
    after_children = not child_terminal_times or root_last_time > max(child_terminal_times)
    root_not_paused = (
        root_flags["livenessState"] != "paused"
        and not root_flags["replayInvalid"]
        and root_last_time > last_yield_time
    )
    complete = (
        is_settled(root_last)
        and all_children_terminal
        and after_children
        and root_not_paused
    )
    return {
        "complete": complete,
        "reason": "complete" if complete else "awaiting_native_resume",
        "root": {
            "path": str(root_path),
            "paths": [str(path) for path in root_paths],
            "terminal": is_settled(root_last),
            "last_time": root_last_time,
            "last_yield_time": last_yield_time,
            **root_flags,
        },
        "children": child_states,
    }

while time.monotonic() < deadline:
    state = snapshot()
    if state["complete"]:
        stable_polls += 1
        if stable_polls >= 5:
            (logs / "openclaw-orchestration-state.json").write_text(
                json.dumps(state, indent=2)
            )
            sys.exit(0)
    else:
        stable_polls = 0
    time.sleep(1)

(logs / "openclaw-orchestration-timeout.json").write_text(
    json.dumps(snapshot(), indent=2)
)
sys.exit(1)
"""
        return _nvm_openclaw("python3 -c " + shlex.quote(script))

    @staticmethod
    def _stop_gateway_command() -> str:
        return (
            "if [ -s /logs/agent/openclaw-gateway.pid ]; then "
            "OPENCLAW_GATEWAY_PID=$(cat /logs/agent/openclaw-gateway.pid); "
            "kill $OPENCLAW_GATEWAY_PID 2>/dev/null || true; "
            "fi"
        )

    @staticmethod
    @override
    def name() -> str:
        return AgentName.OPENCLAW.value

    @override
    def get_version_command(self) -> str | None:
        return _nvm_openclaw("openclaw --version")

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        if self._reuse_preinstalled:
            version_check = _nvm_openclaw("command -v openclaw >/dev/null 2>&1")
            if self._version:
                expected = shlex.quote(f"OpenClaw {self._version}")
                version_check = _nvm_openclaw(
                    "openclaw --version | grep -Fq -- " + expected
                )
            result = await environment.exec(command=version_check)
            if result.return_code == 0:
                return
        await self.ensure_system_dependencies(environment, ("curl", "ca_certificates"))
        timeout = self._install_exec_timeout_sec
        await self.exec_as_agent(
            environment,
            command=(
                "set -o pipefail; "
                "retry_all=$(curl --help all 2>/dev/null | grep -q -- '--retry-all-errors' && echo '--retry-all-errors'); "
                "curl -fsSL --retry 5 --retry-delay 2 $retry_all "
                "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh "
                "| bash"
            ),
            timeout_sec=timeout,
        )
        await self.exec_as_agent(
            environment,
            command=(
                'export NVM_DIR="${NVM_DIR:-$HOME/.nvm}" && . "$NVM_DIR/nvm.sh" && '
                f"nvm install {_OPENCLAW_NODE_VERSION}"
            ),
            timeout_sec=timeout,
        )
        await self.exec_as_agent(
            environment,
            command=_nvm_openclaw("node -v && npm -v"),
            timeout_sec=timeout,
        )
        version_spec = f"@{self._version}" if self._version else "@latest"
        oc_pkg = shlex.quote(f"openclaw{version_spec}")
        await self.exec_as_agent(
            environment,
            command=_nvm_openclaw(
                f"npm install -g {oc_pkg} "
                "--fetch-retries=5 --fetch-retry-mintimeout=20000 "
                "--fetch-retry-maxtimeout=120000"
            ),
            timeout_sec=timeout,
        )
        await self.exec_as_agent(
            environment,
            command=_nvm_openclaw("openclaw --version"),
            timeout_sec=timeout,
        )
        await self.exec_as_root(
            environment,
            command=(
                "for bin in node openclaw; do "
                'BIN_PATH="$(if [ -s ~/.nvm/nvm.sh ]; then '
                f". ~/.nvm/nvm.sh; nvm use {_OPENCLAW_NODE_VERSION} >/dev/null; fi; "
                'command -v "$bin" 2>/dev/null || true)"; '
                'if [ -n "$BIN_PATH" ]; then ln -sf "$BIN_PATH" '
                '"/usr/local/bin/$bin"; fi; done'
            ),
        )

    @staticmethod
    def _load_json_object(raw: str) -> dict[str, Any] | None:
        text = raw.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        return _openclaw_decode_last_json_dict_suffix(text)

    def _parse_stdout(self) -> dict[str, Any] | None:
        output_path = self.logs_dir / "openclaw.txt"
        if not output_path.exists():
            return None
        envelope = self._load_json_object(output_path.read_text())
        if not envelope:
            return None
        result = envelope.get("result")
        if isinstance(result, dict):
            return result
        return envelope

    @staticmethod
    def _provider_env_prefix(provider: str) -> str:
        return provider.upper().replace("-", "_")

    def _model_provider(self) -> str | None:
        if not self.model_name or "/" not in self.model_name:
            return None
        return self.model_name.split("/", 1)[0]

    def _merge_provider_base_url_from_env(self, cfg: dict[str, Any]) -> None:
        provider = self._model_provider()
        if not provider:
            return
        env_key = f"{self._provider_env_prefix(provider)}_BASE_URL"
        base = (self._get_env(env_key) or "").strip()
        if not base:
            return
        models = cfg.setdefault("models", {})
        providers = models.setdefault("providers", {})
        prov = providers.setdefault(provider, {})
        if isinstance(prov, dict) and "baseUrl" not in prov:
            prov["baseUrl"] = base

    def _normalize_provider_models_schema(self, cfg: dict[str, Any]) -> None:
        provider = self._model_provider()
        if not provider:
            return
        models_root = cfg.get("models")
        if not isinstance(models_root, dict):
            return
        providers = models_root.get("providers")
        if not isinstance(providers, dict):
            return
        prov_cfg = providers.get(provider)
        if not isinstance(prov_cfg, dict):
            return

        raw_models = prov_cfg.get("models")
        if not isinstance(raw_models, list):
            prov_cfg["models"] = []

        if len(prov_cfg["models"]) == 0:
            prov_cfg["models"] = [{"id": self.model_name, "name": self.model_name}]

    @staticmethod
    def _configured_env_keys(cfg: dict[str, Any]) -> set[str]:
        keys: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if value.get("source") == "env" and isinstance(value.get("id"), str):
                    keys.add(value["id"])
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
            elif (
                isinstance(value, str)
                and value.startswith("${")
                and value.endswith("}")
            ):
                key = value[2:-1]
                if key:
                    keys.add(key)

        visit(cfg)
        return keys

    def _apply_trustfork_anonymized_roster(self, cfg: dict[str, Any]) -> None:
        defense = self._openclaw_trustfork_defense
        if defense is None or defense["name"] != "anonymize-responses":
            return
        agents = cfg.get("agents")
        entries = agents.get("list") if isinstance(agents, dict) else None
        if not isinstance(entries, list):
            raise ValueError(
                "OpenClaw anonymize-responses requires an agents.list roster"
            )
        by_id = {
            str(entry.get("id")): entry for entry in entries if isinstance(entry, dict)
        }
        for actor in defense["manifest"]["actors"]:
            profile = str(actor["profile"])
            entry = by_id.get(profile)
            if entry is None:
                raise ValueError(
                    f"OpenClaw anonymize-responses could not find {profile}"
                )
            neutral = f"Subagent {actor['slot']}"
            entry["name"] = neutral
            entry["description"] = f"{neutral}."

    @staticmethod
    def _trustfork_identity_attestation(actor: dict[str, Any]) -> str:
        actual = actor["actual_identity"]
        return "; ".join(
            [
                f"Subagent {actor['slot']}",
                f"verified model {actual['display_model']}",
                f"provider {actual['provider']}",
                f"{actual['family']} family",
                f"{actual['tier']} tier",
            ]
        )

    def _apply_trustfork_attested_roster(self, cfg: dict[str, Any]) -> None:
        """Publish check-identity attestations derived from the trusted mapping.

        The defense plugin re-derives the same text from the manifest and
        rejects the roster on any provider/model mismatch.
        """
        defense = self._openclaw_trustfork_defense
        if defense is None or defense["name"] != "check-identity":
            return
        agents = cfg.get("agents")
        entries = agents.get("list") if isinstance(agents, dict) else None
        if not isinstance(entries, list):
            raise ValueError("OpenClaw check-identity requires an agents.list roster")
        by_id = {
            str(entry.get("id")): entry for entry in entries if isinstance(entry, dict)
        }
        for actor in defense["manifest"]["actors"]:
            profile = str(actor["profile"])
            entry = by_id.get(profile)
            if entry is None:
                raise ValueError(f"OpenClaw check-identity could not find {profile}")
            attested = self._trustfork_identity_attestation(actor)
            entry["name"] = attested
            entry["description"] = f"{attested}."

    def _build_full_openclaw_config(self) -> dict[str, Any]:
        cfg = copy.deepcopy(self._SETUP_BASELINE)
        self._deep_merge(cfg, copy.deepcopy(self._DEFAULT_CONFIG))
        self._deep_merge(cfg, copy.deepcopy(self._openclaw_config))
        if self.mcp_servers:
            servers: dict[str, dict[str, Any]] = {}
            for server in self.mcp_servers:
                if server.transport == "stdio":
                    entry: dict[str, Any] = {}
                    if server.command:
                        entry["command"] = server.command
                    if server.args:
                        entry["args"] = server.args
                    servers[server.name] = entry
                elif server.transport == "sse":
                    servers[server.name] = {
                        "url": server.url,
                        "transport": "sse",
                    }
                else:
                    servers[server.name] = {
                        "url": server.url,
                        "transport": "streamable-http",
                    }
            mcp_patch = cfg.setdefault("mcp", {})
            existing = mcp_patch.get("servers")
            merged_servers: dict[str, Any] = (
                dict(existing) if isinstance(existing, dict) else {}
            )
            merged_servers.update(servers)
            mcp_patch["servers"] = merged_servers

        self._merge_provider_base_url_from_env(cfg)
        self._normalize_provider_models_schema(cfg)
        self._merge_harbor_headless_tool_denies(cfg)
        self._apply_trustfork_anonymized_roster(cfg)
        self._apply_trustfork_attested_roster(cfg)

        if self._openclaw_trustfork_roster is not None:
            plugins = cfg.setdefault("plugins", {})
            load = plugins.setdefault("load", {})
            paths = load.setdefault("paths", [])
            plugin_path = f"{self._TRUSTFORK_PLUGIN_DIR}/index.cjs"
            if plugin_path not in paths:
                paths.append(plugin_path)
            allowed = plugins.setdefault("allow", [])
            if self._TRUSTFORK_PLUGIN_ID not in allowed:
                allowed.append(self._TRUSTFORK_PLUGIN_ID)
            entries = plugins.setdefault("entries", {})
            entries[self._TRUSTFORK_PLUGIN_ID] = {
                "enabled": True,
                "hooks": {"allowPromptInjection": True},
            }

        if self._openclaw_trustfork_defense is not None:
            plugin_id = self._trustfork_defense_plugin_id()
            plugins = cfg.setdefault("plugins", {})
            load = plugins.setdefault("load", {})
            paths = load.setdefault("paths", [])
            plugin_path = self._trustfork_defense_plugin_path()
            if plugin_path not in paths:
                paths.append(plugin_path)
            allowed = plugins.setdefault("allow", [])
            if plugin_id not in allowed:
                allowed.append(plugin_id)
            entries = plugins.setdefault("entries", {})
            entries[plugin_id] = {
                "enabled": True,
                "hooks": self._trustfork_defense_hook_permissions(),
            }

        if self._failover_retries is not None:
            auth = cfg.setdefault("auth", {})
            cooldowns = auth.setdefault("cooldowns", {})
            cooldowns["rateLimitedProfileRotations"] = self._failover_retries

        return cfg

    def _trajectory_from_envelope_with_steps(
        self, envelope: dict[str, Any], steps: list[Step]
    ) -> Trajectory | None:
        meta = envelope.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        agent_meta = meta.get("agentMeta")
        session_id = (
            agent_meta.get("sessionId")
            if isinstance(agent_meta, dict)
            and isinstance(agent_meta.get("sessionId"), str)
            else None
        ) or "unknown"
        usage_fm: dict[str, Any] | None = None
        if isinstance(agent_meta, dict):
            u2 = agent_meta.get("usage")
            if isinstance(u2, dict):
                usage_fm = u2
        input_tok_fm = int(usage_fm.get("input") or 0) if usage_fm else 0
        output_tok_fm = int(usage_fm.get("output") or 0) if usage_fm else 0
        cache_read_fm = int(usage_fm.get("cacheRead") or 0) if usage_fm else 0
        prompt_fm = input_tok_fm + cache_read_fm
        final_metrics = FinalMetrics(
            total_prompt_tokens=prompt_fm or None,
            total_completion_tokens=output_tok_fm or None,
            total_cached_tokens=cache_read_fm or None,
            total_steps=len(steps),
        )
        return Trajectory(
            schema_version="ATIF-v1.7",
            session_id=session_id,
            agent=Agent(
                name="openclaw",
                version=self.version() or "unknown",
                model_name=self.model_name,
            ),
            steps=steps,
            final_metrics=final_metrics,
        )

    def _convert_envelope_to_trajectory(
        self, envelope: dict[str, Any], instruction: str
    ) -> Trajectory | None:
        meta = envelope.get("meta")
        if not isinstance(meta, dict):
            meta = {}

        agent_meta = meta.get("agentMeta")
        session_id = (
            agent_meta.get("sessionId")
            if isinstance(agent_meta, dict)
            and isinstance(agent_meta.get("sessionId"), str)
            else None
        ) or "unknown"

        payloads = envelope.get("payloads")
        if not isinstance(payloads, list):
            payloads = []

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        for item in payloads:
            if not isinstance(item, dict):
                continue
            t = item.get("text")
            if not isinstance(t, str) or not t.strip():
                continue
            if item.get("isReasoning") is True:
                reasoning_parts.append(t.strip())
            else:
                text_parts.append(t.strip())

        assistant_text = "\n\n".join(text_parts) if text_parts else ""
        if not assistant_text and isinstance(
            meta.get("finalAssistantVisibleText"), str
        ):
            assistant_text = meta["finalAssistantVisibleText"].strip()

        tool_calls: list[ToolCall] | None = None
        pending = meta.get("pendingToolCalls")
        if isinstance(pending, list):
            calls: list[ToolCall] = []
            for c in pending:
                if not isinstance(c, dict):
                    continue
                name = c.get("name")
                if not isinstance(name, str):
                    continue
                args_raw = c.get("arguments", "")
                if isinstance(args_raw, str):
                    try:
                        args: dict[str, Any] = (
                            json.loads(args_raw) if args_raw.strip() else {}
                        )
                    except json.JSONDecodeError:
                        args = {"raw": args_raw}
                elif isinstance(args_raw, dict):
                    args = args_raw
                else:
                    args = {}
                cid = c.get("id")
                calls.append(
                    ToolCall(
                        tool_call_id=str(cid) if cid is not None else "",
                        function_name=name,
                        arguments=args,
                    )
                )
            if calls:
                tool_calls = calls

        usage: dict[str, Any] | None = None
        if isinstance(agent_meta, dict):
            u = agent_meta.get("usage")
            if isinstance(u, dict):
                usage = u

        input_tok = int(usage.get("input") or 0) if usage else 0
        output_tok = int(usage.get("output") or 0) if usage else 0
        cache_read = int(usage.get("cacheRead") or 0) if usage else 0
        cache_write = int(usage.get("cacheWrite") or 0) if usage else 0

        prompt_for_metrics = input_tok + cache_read
        step_metrics: Metrics | None = None
        if input_tok or output_tok or cache_read:
            step_metrics = Metrics(
                prompt_tokens=prompt_for_metrics or None,
                completion_tokens=output_tok or None,
                cached_tokens=cache_read or None,
                extra=({"cache_write_tokens": cache_write} if cache_write else None),
            )

        steps: list[Step] = [
            Step(
                step_id=1,
                source="user",
                message=instruction,
            ),
        ]
        agent_step_kwargs: dict[str, Any] = {
            "step_id": 2,
            "source": "agent",
            "message": assistant_text or "(no assistant text in JSON output)",
            "model_name": self.model_name,
        }
        if reasoning_parts:
            agent_step_kwargs["reasoning_content"] = "\n\n".join(reasoning_parts)
        if tool_calls:
            agent_step_kwargs["tool_calls"] = tool_calls
        if step_metrics:
            agent_step_kwargs["metrics"] = step_metrics
        steps.append(Step(**agent_step_kwargs))

        final_metrics = FinalMetrics(
            total_prompt_tokens=prompt_for_metrics or None,
            total_completion_tokens=output_tok or None,
            total_cached_tokens=cache_read or None,
            total_steps=len(steps),
        )

        return Trajectory(
            schema_version="ATIF-v1.7",
            session_id=session_id,
            agent=Agent(
                name="openclaw",
                version=self.version() or "unknown",
                model_name=self.model_name,
            ),
            steps=steps,
            final_metrics=final_metrics,
        )

    @staticmethod
    def _bundle_profile(bundle_dir: Path) -> str | None:
        text = str(bundle_dir).lower()
        for profile in ("candidate_a", "candidate_b", "candidate_c", "candidate_d"):
            if profile in text or profile.replace("_", "-") in text:
                return profile

        identity = OpenClaw._bundle_first_string(
            bundle_dir,
            ("agentid", "agent_id", "sessionkey", "session_key"),
        )
        text = (identity or "").lower()
        for profile in ("candidate_a", "candidate_b", "candidate_c", "candidate_d"):
            if profile in text or profile.replace("_", "-") in text:
                return profile
        if text == "main" or "agent:main:" in text:
            return "main"
        return None

    @staticmethod
    def _bundle_first_string(
        bundle_dir: Path,
        keys: tuple[str, ...],
    ) -> str | None:
        def find_key(value: Any, target: str) -> str | None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key.lower() == target and isinstance(child, str) and child:
                        return child
                for child in value.values():
                    found = find_key(child, target)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = find_key(child, target)
                    if found:
                        return found
            return None

        for filename in ("metadata.json", "manifest.json", "artifacts.json"):
            try:
                payload = json.loads(
                    (bundle_dir / filename).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
            for key in keys:
                found = find_key(payload, key)
                if found:
                    return found
        return None

    def _native_bundle_trajectories(
        self, instruction: str
    ) -> tuple[Trajectory | None, list[Trajectory]]:
        root = self.logs_dir / "openclaw-native" / "trajectories"
        if not root.exists():
            return None, []
        parent: Trajectory | None = None
        children: list[Trajectory] = []
        for bundle_dir in sorted({path.parent for path in root.rglob("manifest.json")}):
            profile = self._bundle_profile(bundle_dir)
            resolved_model = (
                self._bundle_first_string(
                    bundle_dir,
                    ("resolvedmodel", "resolved_model", "modelid", "model_id", "model"),
                )
                or self.model_name
            )
            steps = openclaw_bundle_to_atif_steps(
                bundle_dir,
                instruction=instruction if profile == "main" else "",
                model_name=resolved_model or "",
            )
            if not steps:
                continue
            session_id = (
                self._bundle_first_string(bundle_dir, ("sessionid", "session_id"))
                or bundle_dir.name
            )
            prompt_tokens = sum(
                step.metrics.prompt_tokens or 0
                for step in steps
                if step.metrics is not None
            )
            completion_tokens = sum(
                step.metrics.completion_tokens or 0
                for step in steps
                if step.metrics is not None
            )
            cached_tokens = sum(
                step.metrics.cached_tokens or 0
                for step in steps
                if step.metrics is not None
            )
            trajectory = Trajectory(
                schema_version="ATIF-v1.7",
                session_id=session_id,
                trajectory_id=(
                    f"openclaw-native:{session_id}"
                    if profile and profile != "main"
                    else None
                ),
                agent=Agent(
                    name=(profile if profile and profile != "main" else "openclaw"),
                    version=self.version() or "unknown",
                    model_name=resolved_model,
                    extra={"native_bundle": str(bundle_dir.relative_to(self.logs_dir))},
                ),
                steps=steps,
                final_metrics=FinalMetrics(
                    total_prompt_tokens=prompt_tokens or None,
                    total_completion_tokens=completion_tokens or None,
                    total_cached_tokens=cached_tokens or None,
                    total_steps=len(steps),
                ),
            )
            if profile == "main":
                parent = trajectory
            elif profile and profile.startswith("candidate_"):
                children.append(trajectory)

        raw_root = self.logs_dir / "openclaw-native" / "raw-state"
        lifecycle_path = self.logs_dir / "openclaw-orchestration-state.json"
        try:
            lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lifecycle = {}
        lifecycle_root = lifecycle.get("root") if isinstance(lifecycle, dict) else None
        root_sources: list[str] = []
        if isinstance(lifecycle_root, dict):
            raw_sources = lifecycle_root.get("paths")
            if isinstance(raw_sources, list):
                root_sources.extend(
                    source for source in raw_sources if isinstance(source, str)
                )
            legacy_source = lifecycle_root.get("path")
            if isinstance(legacy_source, str) and legacy_source not in root_sources:
                root_sources.insert(0, legacy_source)
        raw_parent_paths = [
            raw_root / "main" / "sessions" / Path(source).name
            for source in root_sources
        ]
        raw_parent_paths = [path for path in raw_parent_paths if path.is_file()]
        if raw_parent_paths:
            raw_parent_steps: list[Step] = []
            for index, raw_parent_path in enumerate(raw_parent_paths):
                continuation_steps = openclaw_session_jsonl_to_atif_steps(
                    raw_parent_path,
                    instruction=instruction if index == 0 else "",
                    model_name=self.model_name or "",
                )
                if continuation_steps:
                    raw_parent_steps.extend(continuation_steps)
            for step_id, step in enumerate(raw_parent_steps, start=1):
                step.step_id = step_id
            if raw_parent_steps:
                prompt_tokens = sum(
                    step.metrics.prompt_tokens or 0
                    for step in raw_parent_steps
                    if step.metrics is not None
                )
                completion_tokens = sum(
                    step.metrics.completion_tokens or 0
                    for step in raw_parent_steps
                    if step.metrics is not None
                )
                cached_tokens = sum(
                    step.metrics.cached_tokens or 0
                    for step in raw_parent_steps
                    if step.metrics is not None
                )
                parent = Trajectory(
                    schema_version="ATIF-v1.7",
                    session_id=raw_parent_paths[0].stem,
                    agent=Agent(
                        name="openclaw",
                        version=self.version() or "unknown",
                        model_name=self.model_name,
                        extra={
                            "native_raw_canonical": str(
                                raw_parent_paths[0].relative_to(self.logs_dir)
                            ),
                            "native_raw_continuations": [
                                str(path.relative_to(self.logs_dir))
                                for path in raw_parent_paths[1:]
                            ],
                        },
                    ),
                    steps=raw_parent_steps,
                    final_metrics=FinalMetrics(
                        total_prompt_tokens=prompt_tokens or None,
                        total_completion_tokens=completion_tokens or None,
                        total_cached_tokens=cached_tokens or None,
                        total_steps=len(raw_parent_steps),
                    ),
                )

        seen_child_sessions = {child.session_id for child in children}
        model_by_profile = {
            str(row.get("name")): str(row.get("model") or self.model_name or "")
            for row in (self._openclaw_trustfork_roster or [])
        }
        for profile_dir in sorted(raw_root.glob("candidate_*")):
            profile = profile_dir.name
            for session_path in sorted((profile_dir / "sessions").glob("*.jsonl")):
                if session_path.name.endswith(".trajectory.jsonl"):
                    continue
                session_id = session_path.stem
                if session_id in seen_child_sessions:
                    continue
                resolved_model = model_by_profile.get(profile, self.model_name or "")
                steps = openclaw_session_jsonl_to_atif_steps(
                    session_path,
                    instruction="",
                    model_name=resolved_model,
                )
                if not steps:
                    continue
                children.append(
                    Trajectory(
                        schema_version="ATIF-v1.7",
                        session_id=session_id,
                        trajectory_id=f"openclaw-native:{session_id}",
                        agent=Agent(
                            name=profile,
                            version=self.version() or "unknown",
                            model_name=resolved_model,
                            extra={
                                "native_raw_fallback": str(
                                    session_path.relative_to(self.logs_dir)
                                )
                            },
                        ),
                        steps=steps,
                        final_metrics=FinalMetrics(total_steps=len(steps)),
                    )
                )
                seen_child_sessions.add(session_id)
        return parent, children

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        envelope = self._parse_stdout()
        instruction_path = self.logs_dir / "instruction.txt"
        instruction = ""
        try:
            if instruction_path.exists():
                instruction = instruction_path.read_text()
        except OSError:
            pass

        try:
            trajectory = None
            native_parent, native_children = self._native_bundle_trajectories(
                instruction
            )
            if native_parent is not None:
                trajectory = native_parent
            if self._use_openclaw_session_jsonl_for_steps:
                session_path = self.logs_dir / "openclaw.session.jsonl"
                session_steps = openclaw_session_jsonl_to_atif_steps(
                    session_path,
                    instruction=instruction,
                    model_name=self.model_name or "",
                )
                if session_steps and trajectory is None and envelope is not None:
                    trajectory = self._trajectory_from_envelope_with_steps(
                        envelope, session_steps
                    )
            if trajectory is None and envelope is not None:
                trajectory = self._convert_envelope_to_trajectory(envelope, instruction)
        except Exception:
            self.logger.exception("Failed to convert OpenClaw JSON to trajectory")
            return

        if not trajectory:
            return

        trajectory.subagent_trajectories = native_children or None
        if native_children:
            metrics = [
                item
                for item in [trajectory.final_metrics]
                + [child.final_metrics for child in native_children]
                if item is not None
            ]
            trajectory.final_metrics = FinalMetrics(
                total_prompt_tokens=sum(
                    item.total_prompt_tokens or 0 for item in metrics
                )
                or None,
                total_completion_tokens=sum(
                    item.total_completion_tokens or 0 for item in metrics
                )
                or None,
                total_cached_tokens=sum(
                    item.total_cached_tokens or 0 for item in metrics
                )
                or None,
                total_cost_usd=sum(item.total_cost_usd or 0 for item in metrics)
                or None,
                total_steps=len(trajectory.steps),
                extra={"subagent_count": len(native_children)},
            )

        trajectory_path = self.logs_dir / "trajectory.json"
        try:
            trajectory_path.write_text(
                format_trajectory_json(trajectory.to_json_dict())
            )
            self.logger.debug(f"Wrote OpenClaw trajectory to {trajectory_path}")
        except OSError as exc:
            self.logger.debug(
                f"Failed to write trajectory file {trajectory_path}: {exc}"
            )

        if trajectory.final_metrics:
            fm = trajectory.final_metrics
            context.cost_usd = fm.total_cost_usd
            context.n_input_tokens = fm.total_prompt_tokens or 0
            context.n_output_tokens = fm.total_completion_tokens or 0
            context.n_cache_tokens = fm.total_cached_tokens or 0

    def _build_register_skills_command(self) -> str | None:
        if not self.skills_dir:
            return None
        return (
            f"mkdir -p ~/.openclaw/skills && "
            f"cp -r {shlex.quote(self.skills_dir)}/* "
            f"~/.openclaw/skills/ 2>/dev/null || true"
        )

    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        escaped_instruction = shlex.quote(instruction)

        if not self.model_name or "/" not in self.model_name:
            raise ValueError("Model name must be in the format provider/model_name")

        provider, _ = self.model_name.split("/", 1)
        self._validate_provider(provider)

        env: dict[str, str] = {}
        keys = set(self._provider_env_keys(provider))
        keys.update(self._configured_env_keys(self._openclaw_config))
        self.logger.debug(
            "OpenClaw forwarding env vars for provider %r: %s",
            provider,
            sorted(keys),
        )

        for key in keys:
            val = self._get_env(key)
            if val:
                env[key] = val
            else:
                self.logger.debug("Missing optional env key for OpenClaw run: %s", key)

        upload_path = self.logs_dir / self._UPLOAD_CONFIG_FILENAME
        upload_path.write_text(
            json.dumps(
                self._build_full_openclaw_config(),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        try:
            instruction_path = self.logs_dir / "instruction.txt"
            instruction_path.write_text(instruction)
        except OSError:
            pass

        await self.exec_as_agent(
            environment,
            command=_nvm_openclaw(self._SETUP_CLI),
            env=env,
        )

        await self.exec_as_agent(
            environment,
            command=self._shell_install_uploaded_config(),
            env=env,
        )
        await self._install_trustfork_profile_plugin(environment, env)
        await self._patch_trustfork_sessions_spawn_schema(environment, env)
        await self._apply_openclaw_batch_wake_backport(environment, env)
        await self._install_trustfork_defense_plugin(environment, env)

        skills_command = self._build_register_skills_command()
        if skills_command:
            await self.exec_as_agent(environment, command=skills_command, env=env)

        cli_flags = self.build_cli_flags()
        cli_flags_arg = (cli_flags + " ") if cli_flags else ""
        parent_session_key = self._parent_session_key()
        command = _nvm_openclaw(
            f"openclaw agent --json {cli_flags_arg}"
            f"--session-key {shlex.quote(parent_session_key)} "
            f"--model {shlex.quote(self.model_name)} "
            f"--message {escaped_instruction} "
            f"2>/logs/agent/openclaw.stderr.txt </dev/null "
            f"| stdbuf -oL tee /logs/agent/openclaw.txt"
        )
        self.logger.debug("OpenClaw agent env keys: %s", sorted(env))
        self.logger.debug("OpenClaw agent command: %s", command)
        gateway_task = await self._start_gateway(environment, env)
        try:
            await self.exec_as_agent(environment, command, env=env)
            await self.exec_as_agent(
                environment,
                command=self._wait_for_native_orchestration_command(),
                env=env,
            )
            await self._copy_openclaw_session_file_to_agent_logs(environment, env)
            await self._export_native_trajectories(environment, env)
        finally:
            await self._stop_gateway(environment, env, gateway_task)
