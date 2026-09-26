from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, override

from packaging.version import InvalidVersion, Version

from harbor.agents.installed.base import (
    BaseInstalledAgent,
    CliFlag,
    NonZeroAgentExitCodeError,
    with_prompt_template,
)
from harbor.agents.installed.node_install import nvm_node_install_snippet
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
    SubagentTrajectoryRef,
    ToolCall,
    Trajectory,
)
from harbor.utils.trajectory_utils import format_trajectory_json


_CURRENT_PI_PACKAGE = "@earendil-works/pi-coding-agent"
_LEGACY_PI_PACKAGE = "@mariozechner/pi-coding-agent"
_PI_PACKAGE_RENAME_VERSION = Version("0.74.0")
_PI_AGENT_DIR = "/root/.pi/agent"
_PI_SETTINGS_REMOTE = f"{_PI_AGENT_DIR}/settings.json"
_PI_SUBAGENTS_REMOTE = f"{_PI_AGENT_DIR}/subagents.json"
_PI_AGENTS_REMOTE = f"{_PI_AGENT_DIR}/agents"
_PI_EXTENSIONS_REMOTE = f"{_PI_AGENT_DIR}/extensions"
_PI_MODELS_REMOTE = f"{_PI_AGENT_DIR}/models.json"
_BUILTIN_CHILD_TOOLS = ("read", "bash", "edit", "write", "grep", "find", "ls")
_TRUSTFORK_PI_SUBAGENTS = "npm:@tintinweb/pi-subagents@0.15.0"
_TRUSTFORK_DEFENSES = {
    "anonymize-responses",
    "check-identity",
    "verify-before-action",
}
_TRUSTFORK_DEFENSE_FILENAME = "trustfork-defense.js"
_TRUSTFORK_DEFENSE_MANIFEST_MARKER = "__TRUSTFORK_DEFENSE_MANIFEST__"


class Pi(BaseInstalledAgent):
    SUPPORTS_ATIF: bool = True
    SUPPORTS_RESUME: bool = True

    _OUTPUT_FILENAME = "pi.txt"

    CLI_FLAGS = [
        CliFlag(
            "thinking",
            cli="--thinking",
            type="enum",
            choices=["off", "minimal", "low", "medium", "high", "xhigh"],
        ),
    ]

    def __init__(
        self,
        *args: Any,
        pi_models_config: dict[str, Any] | None = None,
        pi_subagent_roster: list[dict[str, Any]] | None = None,
        pi_root_tools: list[str] | None = None,
        pi_trustfork_defense: dict[str, Any] | None = None,
        reuse_preinstalled: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._pi_models_config = pi_models_config
        self._pi_subagent_roster = pi_subagent_roster
        self._pi_root_tools = pi_root_tools
        self._pi_trustfork_defense = pi_trustfork_defense
        self._reuse_preinstalled = reuse_preinstalled
        self._instruction: str | None = None
        self._validate_trustfork_config()

    def _validate_trustfork_config(self) -> None:
        self._validate_trustfork_defense()
        if self._pi_subagent_roster is None:
            if self._pi_trustfork_defense is not None:
                raise ValueError("pi_trustfork_defense requires a Pi subagent roster")
            return
        expected = ["candidate_a", "candidate_b", "candidate_c", "candidate_d"]
        names = [str(row.get("name")) for row in self._pi_subagent_roster]
        if names != expected:
            raise ValueError(
                "pi_subagent_roster must contain candidate_a through candidate_d "
                "in fixed order"
            )
        for row in self._pi_subagent_roster:
            tools = row.get("tools")
            if tools != list(_BUILTIN_CHILD_TOOLS):
                raise ValueError(
                    f"Pi child {row['name']} must expose exactly the standard work tools"
                )
            if (
                "model" not in row
                or "description" not in row
                or "systemPrompt" not in row
            ):
                raise ValueError(f"Incomplete Pi child profile: {row['name']}")
            if not isinstance(row["systemPrompt"], str):
                raise ValueError(f"Invalid Pi child system prompt: {row['name']}")
            if row.get("promptMode") not in {"append", "replace"}:
                raise ValueError(f"Invalid Pi child prompt mode: {row['name']}")
        if self._pi_root_tools != [
            "Agent",
            "get_subagent_result",
            "steer_subagent",
        ]:
            raise ValueError(
                "TrustFork Pi root must expose the native foreground/background "
                "delegation tools"
            )
        if self._pi_trustfork_defense is not None:
            for row, actor in zip(
                self._pi_subagent_roster,
                self._pi_trustfork_defense["manifest"]["actors"],
                strict=True,
            ):
                actual_identity = actor["actual_identity"]
                expected_model = (
                    f"{actual_identity['provider']}/{actual_identity['api_model']}"
                )
                if row["name"] != actor["profile"] or row["model"] != expected_model:
                    raise ValueError(
                        "Pi TrustFork defense roster does not match its runtime manifest"
                    )

    def _validate_trustfork_defense(self) -> None:
        config = self._pi_trustfork_defense
        if config is None:
            return
        if not isinstance(config, dict) or set(config) != {
            "name",
            "manifest",
            "source",
        }:
            raise ValueError(
                "pi_trustfork_defense must contain exactly name, manifest, and source"
            )
        name = config["name"]
        manifest = config["manifest"]
        source = config["source"]
        if name not in _TRUSTFORK_DEFENSES:
            raise ValueError(f"Unsupported Pi TrustFork defense: {name}")
        if not isinstance(manifest, dict):
            raise ValueError("Pi TrustFork defense manifest must be an object")
        if manifest.get("schema_version") != "trustfork-defense-manifest-v1":
            raise ValueError("Invalid Pi TrustFork defense manifest schema")
        if manifest.get("defense") != name:
            raise ValueError("Pi TrustFork defense name does not match its manifest")
        actors = manifest.get("actors")
        expected_profiles = [f"candidate_{slot}" for slot in "abcd"]
        if (
            not isinstance(actors, list)
            or [
                actor.get("profile") if isinstance(actor, dict) else None
                for actor in actors
            ]
            != expected_profiles
        ):
            raise ValueError(
                "Pi TrustFork defense manifest must contain the four candidate profiles"
            )
        for slot, actor in zip("ABCD", actors, strict=True):
            if not isinstance(actor, dict):
                raise ValueError("Invalid Pi TrustFork defense actor")
            actual_identity = actor.get("actual_identity")
            if actor.get("slot") != slot or not isinstance(
                actor.get("displayed_identity"), str
            ):
                raise ValueError("Invalid Pi TrustFork defense actor identity")
            if not isinstance(actual_identity, dict):
                raise ValueError("Invalid Pi TrustFork defense runtime identity")
            identity_values = [
                actual_identity.get(key)
                for key in (
                    "provider",
                    "api_model",
                    "display_model",
                    "family",
                    "tier",
                )
            ]
            if not all(isinstance(value, str) and value for value in identity_values):
                raise ValueError("Invalid Pi TrustFork defense runtime identity")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Pi TrustFork defense source must be non-empty text")
        if _TRUSTFORK_DEFENSE_MANIFEST_MARKER in source:
            raise ValueError(
                "Pi TrustFork defense source still contains its manifest marker"
            )
        rendered_manifest = json.dumps(
            manifest, ensure_ascii=False, separators=(",", ":")
        )
        if rendered_manifest not in source:
            raise ValueError(
                "Pi TrustFork defense source does not contain the supplied manifest"
            )

    @staticmethod
    @override
    def name() -> str:
        return AgentName.PI.value

    @override
    def get_version_command(self) -> str | None:
        return ". ~/.nvm/nvm.sh; pi --version"

    @override
    def parse_version(self, stdout: str) -> str:
        return stdout.strip().splitlines()[-1].strip()

    def _package_name(self) -> str:
        if self._version:
            try:
                if Version(self._version) < _PI_PACKAGE_RENAME_VERSION:
                    return _LEGACY_PI_PACKAGE
            except InvalidVersion:
                pass
        return _CURRENT_PI_PACKAGE

    async def _install_trustfork_config(self, environment: BaseEnvironment) -> None:
        if self._pi_subagent_roster is None:
            return
        if self._pi_models_config is None:
            raise ValueError("pi_models_config is required with a Pi subagent roster")
        await self.exec_as_agent(
            environment,
            command=f"mkdir -p {_PI_AGENTS_REMOTE} {_PI_EXTENSIONS_REMOTE}",
        )
        await self._upload_config_text(
            environment,
            content=json.dumps(
                {
                    "packages": [_TRUSTFORK_PI_SUBAGENTS],
                    "enabledModels": [
                        f"{provider_id}/{model['id']}"
                        for provider_id, provider in self._pi_models_config.get(
                            "providers", {}
                        ).items()
                        for model in provider.get("models", [])
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            remote_path=_PI_SETTINGS_REMOTE,
            filename="settings.json",
        )
        await self._upload_config_text(
            environment,
            content=json.dumps(
                {
                    "maxConcurrent": 4,
                    "schedulingEnabled": False,
                    "scopeModels": True,
                    "strictAgentFiles": True,
                    "disableDefaultAgents": True,
                    "fleetView": False,
                    "widgetMode": "off",
                    "maxSubagentDepth": 1,
                    "fallbackSubagent": "none",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            remote_path=_PI_SUBAGENTS_REMOTE,
            filename="subagents.json",
        )
        for row in self._pi_subagent_roster:
            frontmatter = [
                "---",
                f"description: {json.dumps(row['description'], ensure_ascii=False)}",
                f"model: {json.dumps(row['model'])}",
                f"tools: {','.join(row['tools'])}",
                "output_transcript: true",
                f"persist_session: {str(bool(row.get('persistSession'))).lower()}",
                f"session_dir: {json.dumps(row.get('sessionDir', ''))}",
                f"prompt_mode: {row['promptMode']}",
                "---",
                "",
                row["systemPrompt"],
                "",
            ]
            await self._upload_config_text(
                environment,
                content="\n".join(frontmatter),
                remote_path=f"{_PI_AGENTS_REMOTE}/{row['name']}.md",
                filename=f"{row['name']}.md",
            )
        await self._upload_config_text(
            environment,
            content=json.dumps(
                self._resolve_config_env(self._pi_models_config),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            remote_path=_PI_MODELS_REMOTE,
            filename="models.json",
        )
        defense_path: str | None = None
        if self._pi_trustfork_defense is not None:
            defense_path = f"{_PI_EXTENSIONS_REMOTE}/{_TRUSTFORK_DEFENSE_FILENAME}"
            await self._upload_config_text(
                environment,
                content=self._pi_trustfork_defense["source"],
                remote_path=defense_path,
                filename=_TRUSTFORK_DEFENSE_FILENAME,
            )
        protected_paths = [
            _PI_SETTINGS_REMOTE,
            _PI_SUBAGENTS_REMOTE,
            _PI_MODELS_REMOTE,
            f"{_PI_AGENTS_REMOTE}/*.md",
        ]
        if defense_path is not None:
            protected_paths.append(defense_path)
        await self.exec_as_agent(
            environment,
            command=f"chmod 600 {' '.join(protected_paths)}",
        )

    def _resolve_config_env(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve_config_env(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_config_env(item) for item in value]
        if isinstance(value, str) and value.startswith("{env:") and value.endswith("}"):
            key = value[5:-1]
            resolved = self._get_env(key)
            if not resolved:
                raise ValueError(
                    f"Missing Pi configuration environment variable: {key}"
                )
            return resolved
        return value

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        installed = False
        if self._reuse_preinstalled:
            expected = shlex.quote(self._version) if self._version else ""
            version_check = (
                f'test "$(pi --version | tail -n 1 | tr -d "\\r")" = {expected}'
                if expected
                else "pi --version >/dev/null"
            )
            try:
                await self.exec_as_agent(
                    environment,
                    command=f"command -v pi >/dev/null 2>&1 && {version_check}",
                )
            except NonZeroAgentExitCodeError:
                pass
            else:
                installed = True

        if not installed:
            await self.ensure_system_dependencies(environment, ("curl",))
            version_spec = f"@{self._version}" if self._version else "@latest"
            package_name = self._package_name()
            await self.exec_as_agent(
                environment,
                command=(
                    "set -euo pipefail; "
                    f"{nvm_node_install_snippet()} && "
                    f"npm install -g --ignore-scripts {package_name}{version_spec} && "
                    "pi --version"
                ),
            )
        await self._install_trustfork_config(environment)

    def _build_register_skills_command(self) -> str | None:
        if not self.skills_dir:
            return None
        return (
            f"mkdir -p $HOME/.agents/skills && "
            f"cp -r {shlex.quote(self.skills_dir)}/* "
            f"$HOME/.agents/skills/ 2>/dev/null || true"
        )

    @override
    @with_prompt_template
    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        self._instruction = instruction
        escaped_instruction = shlex.quote(instruction)

        if not self.model_name or "/" not in self.model_name:
            raise ValueError("Model name must be in the format provider/model_name")

        provider, model = self.model_name.split("/", 1)
        env: dict[str, str] = {}
        keys: list[str] = []

        if provider == "amazon-bedrock":
            keys.extend(["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"])
        elif provider == "anthropic":
            keys.extend(
                ["ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_BASE_URL"]
            )
        elif provider == "github-copilot":
            keys.append("GITHUB_TOKEN")
        elif provider == "google":
            keys.extend(
                [
                    "GEMINI_API_KEY",
                    "GOOGLE_GENERATIVE_AI_API_KEY",
                    "GOOGLE_APPLICATION_CREDENTIALS",
                    "GOOGLE_CLOUD_PROJECT",
                    "GOOGLE_CLOUD_LOCATION",
                    "GOOGLE_GENAI_USE_VERTEXAI",
                    "GOOGLE_API_KEY",
                ]
            )
        elif provider == "groq":
            keys.append("GROQ_API_KEY")
        elif provider == "huggingface":
            keys.append("HF_TOKEN")
        elif provider == "mistral":
            keys.append("MISTRAL_API_KEY")
        elif provider == "openai":
            keys.extend(["OPENAI_API_KEY", "OPENAI_BASE_URL"])
        elif provider == "openrouter":
            keys.append("OPENROUTER_API_KEY")
        elif provider == "xai":
            keys.append("XAI_API_KEY")

        if self._pi_models_config:
            for provider_config in self._pi_models_config.get("providers", {}).values():
                api_key = provider_config.get("apiKey")
                if isinstance(api_key, str) and api_key.startswith("$"):
                    keys.append(api_key.removeprefix("$").strip("{}"))
                for value in (provider_config.get("headers") or {}).values():
                    if isinstance(value, str) and value.startswith("$"):
                        keys.append(value.removeprefix("$").strip("{}"))

        for key in dict.fromkeys(keys):
            value = self._get_env(key)
            if value:
                env[key] = value

        model_args = f"--provider {shlex.quote(provider)} --model {shlex.quote(model)} "
        tool_args = ""
        if self._pi_root_tools is not None:
            tool_args = f"--tools {shlex.quote(','.join(self._pi_root_tools))} "
        cli_flags = self.build_cli_flags()
        if cli_flags:
            cli_flags += " "
        resume_flag = "--continue " if self._resume else ""

        skills_command = self._build_register_skills_command()
        if skills_command:
            await self.exec_as_agent(environment, command=skills_command)

        await self.exec_as_agent(
            environment,
            command=(
                ". ~/.nvm/nvm.sh; set -o pipefail; "
                "pi --print --mode json --session-dir /logs/agent/pi/sessions "
                f"{resume_flag}{model_args}{tool_args}{cli_flags}{escaped_instruction} "
                '2>&1 </dev/null | grep -v \'"type":"message_update"\' '
                f"| stdbuf -oL tee /logs/agent/{self._OUTPUT_FILENAME}"
            ),
            env=env,
        )

    @staticmethod
    def _message_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        return "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and part.get("text")
        )

    @staticmethod
    def _message_reasoning(content: Any) -> str | None:
        if not isinstance(content, list):
            return None
        values = [
            str(part.get("thinking") or "")
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "thinking"
            and part.get("thinking")
        ]
        return "\n\n".join(values) or None

    @staticmethod
    def _metrics(message: dict[str, Any]) -> Metrics | None:
        usage = message.get("usage")
        if not isinstance(usage, dict):
            return None
        cost = usage.get("cost") or {}
        prompt = int(usage.get("input") or 0) + int(usage.get("cacheRead") or 0)
        completion = int(usage.get("output") or 0)
        cached = int(usage.get("cacheRead") or 0)
        total_cost = float(cost.get("total") or 0)
        if not any((prompt, completion, cached, total_cost)):
            return None
        return Metrics(
            prompt_tokens=prompt or None,
            completion_tokens=completion or None,
            cached_tokens=cached or None,
            cost_usd=total_cost or None,
        )

    def _parse_stdout_messages(self) -> tuple[str | None, list[dict[str, Any]]]:
        output_file = self.logs_dir / self._OUTPUT_FILENAME
        if not output_file.exists():
            return None, []
        messages: list[dict[str, Any]] = []
        for line in output_file.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") in {"message_end", "tool_result_end"}:
                message = event.get("message")
                if isinstance(message, dict):
                    messages.append(message)
        return None, messages

    def _parse_session_messages(self) -> tuple[str | None, list[dict[str, Any]]]:
        session_root = self.logs_dir / "pi" / "sessions"
        files = list(session_root.rglob("*.jsonl")) if session_root.exists() else []
        if not files:
            return self._parse_stdout_messages()
        latest = max(files, key=lambda path: path.stat().st_mtime_ns)
        session_id: str | None = None
        messages: list[dict[str, Any]] = []
        for line in latest.read_text().splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "session":
                session_id = str(entry.get("id") or "") or None
            elif entry.get("type") == "message" and isinstance(
                entry.get("message"), dict
            ):
                messages.append(entry["message"])
        return session_id, messages

    @staticmethod
    def _read_pi_session(path: Path) -> tuple[str | None, list[dict[str, Any]]]:
        session_id: str | None = None
        messages: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") == "session":
                session_id = str(entry.get("id") or "") or None
            elif entry.get("type") == "message" and isinstance(
                entry.get("message"), dict
            ):
                messages.append(entry["message"])
        return session_id, messages

    def _parse_native_subagent_sessions(self) -> list[Trajectory]:
        session_root = self.logs_dir / "pi" / "subagents"
        if not session_root.exists():
            return []
        trajectories: list[Trajectory] = []
        for path in sorted(session_root.rglob("*.jsonl")):
            profile = next(
                (part for part in path.parts if part.startswith("candidate_")),
                "unknown",
            )
            session_id, messages = self._read_pi_session(path)
            trajectory = self._messages_to_trajectory(
                messages,
                agent_name=profile,
                default_model=None,
                session_id=session_id,
                trajectory_id=f"pi-native:{session_id or path.stem}",
                allow_subagents=False,
            )
            if trajectory is not None:
                trajectories.append(trajectory)
        return trajectories

    def _messages_to_trajectory(
        self,
        messages: list[dict[str, Any]],
        *,
        agent_name: str,
        default_model: str | None,
        session_id: str | None,
        trajectory_id: str | None = None,
        fallback_user_message: str | None = None,
        allow_subagents: bool = False,
    ) -> Trajectory | None:
        steps: list[Step] = []
        call_steps: dict[str, int] = {}
        embedded: list[Trajectory] = []

        for message in messages:
            role = message.get("role")
            if role == "user":
                text = self._message_text(message.get("content"))
                if text:
                    steps.append(
                        Step(
                            step_id=len(steps) + 1,
                            timestamp=self._timestamp(message.get("timestamp")),
                            source="user",
                            message=text,
                        )
                    )
                continue
            if role == "assistant":
                content = message.get("content")
                tool_calls: list[ToolCall] = []
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict) or part.get("type") != "toolCall":
                            continue
                        call_id = str(
                            part.get("id") or f"pi-call-{len(call_steps) + 1}"
                        )
                        arguments = part.get("arguments")
                        if not isinstance(arguments, dict):
                            arguments = {}
                        tool_calls.append(
                            ToolCall(
                                tool_call_id=call_id,
                                function_name=str(part.get("name") or "unknown"),
                                arguments=arguments,
                            )
                        )
                provider = str(message.get("provider") or "")
                model = str(message.get("model") or "")
                model_name = (
                    f"{provider}/{model}"
                    if provider and model
                    else model or default_model
                )
                metrics = self._metrics(message)
                step = Step(
                    step_id=len(steps) + 1,
                    timestamp=self._timestamp(message.get("timestamp")),
                    source="agent",
                    model_name=model_name,
                    message=self._message_text(content),
                    reasoning_content=self._message_reasoning(content),
                    tool_calls=tool_calls or None,
                    metrics=metrics,
                    llm_call_count=1,
                )
                steps.append(step)
                for call in tool_calls:
                    call_steps[call.tool_call_id] = len(steps) - 1
                continue
            if role != "toolResult":
                continue
            call_id = str(message.get("toolCallId") or "")
            step_index = call_steps.get(call_id)
            if step_index is None:
                continue
            refs: list[SubagentTrajectoryRef] = []
            tool_name = str(message.get("toolName") or "").lower()
            if allow_subagents and tool_name in {"subagent", "agent"}:
                details = message.get("details") or {}
                legacy_results = details.get("results") or []
                for result_index, result in enumerate(legacy_results, start=1):
                    if not isinstance(result, dict):
                        continue
                    child_id = f"pi-subagent-{call_id}-{result_index}"
                    child = self._messages_to_trajectory(
                        [
                            row
                            for row in result.get("messages") or []
                            if isinstance(row, dict)
                        ],
                        agent_name=str(result.get("agent") or "unknown"),
                        default_model=str(result.get("model") or "") or None,
                        session_id=session_id,
                        trajectory_id=child_id,
                        fallback_user_message=f"Task: {result.get('task') or ''}",
                        allow_subagents=False,
                    )
                    if child is not None:
                        embedded.append(child)
                        refs.append(
                            SubagentTrajectoryRef(
                                trajectory_id=child_id,
                                session_id=session_id,
                            )
                        )
            observation = ObservationResult(
                source_call_id=call_id,
                content=self._message_text(message.get("content")),
                subagent_trajectory_ref=refs or None,
                extra={"is_error": bool(message.get("isError"))},
            )
            step = steps[step_index]
            if step.observation is None:
                step.observation = Observation(results=[observation])
            else:
                step.observation.results.append(observation)

        if fallback_user_message and not any(step.source == "user" for step in steps):
            steps.insert(
                0,
                Step(step_id=1, source="user", message=fallback_user_message),
            )
            for index, step in enumerate(steps, start=1):
                step.step_id = index
        if not steps:
            return None

        own_metrics = self._final_metrics(steps)
        child_prompt = sum(
            (child.final_metrics.total_prompt_tokens or 0)
            for child in embedded
            if child.final_metrics
        )
        child_completion = sum(
            (child.final_metrics.total_completion_tokens or 0)
            for child in embedded
            if child.final_metrics
        )
        child_cached = sum(
            (child.final_metrics.total_cached_tokens or 0)
            for child in embedded
            if child.final_metrics
        )
        child_cost = sum(
            (child.final_metrics.total_cost_usd or 0)
            for child in embedded
            if child.final_metrics
        )
        final_metrics = FinalMetrics(
            total_prompt_tokens=(own_metrics.total_prompt_tokens or 0) + child_prompt
            or None,
            total_completion_tokens=(own_metrics.total_completion_tokens or 0)
            + child_completion
            or None,
            total_cached_tokens=(own_metrics.total_cached_tokens or 0) + child_cached
            or None,
            total_cost_usd=(own_metrics.total_cost_usd or 0) + child_cost or None,
            total_steps=len(steps),
        )
        return Trajectory(
            schema_version="ATIF-v1.7",
            session_id=session_id or "unknown",
            trajectory_id=trajectory_id,
            agent=Agent(
                name=agent_name,
                version=self.version() or "unknown",
                model_name=default_model,
            ),
            steps=steps,
            final_metrics=final_metrics,
            subagent_trajectories=embedded or None,
        )

    @staticmethod
    def _timestamp(value: Any) -> str | None:
        if value is None:
            return None
        try:
            from datetime import datetime, timezone

            return datetime.fromtimestamp(
                float(value) / 1000, tz=timezone.utc
            ).isoformat()
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    @staticmethod
    def _final_metrics(steps: list[Step]) -> FinalMetrics:
        prompt = completion = cached = 0
        cost = 0.0
        for step in steps:
            if step.metrics is None:
                continue
            prompt += step.metrics.prompt_tokens or 0
            completion += step.metrics.completion_tokens or 0
            cached += step.metrics.cached_tokens or 0
            cost += step.metrics.cost_usd or 0
        return FinalMetrics(
            total_prompt_tokens=prompt or None,
            total_completion_tokens=completion or None,
            total_cached_tokens=cached or None,
            total_cost_usd=cost or None,
            total_steps=len(steps),
        )

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        session_id, messages = self._parse_session_messages()
        trajectory = self._messages_to_trajectory(
            messages,
            agent_name="pi",
            default_model=self.model_name,
            session_id=session_id,
            fallback_user_message=self._instruction,
            allow_subagents=True,
        )
        if trajectory is None:
            if (self.logs_dir / self._OUTPUT_FILENAME).exists():
                context.n_input_tokens = 0
                context.n_output_tokens = 0
                context.n_cache_tokens = 0
            return
        native_children = self._parse_native_subagent_sessions()
        if native_children:
            existing = trajectory.subagent_trajectories or []
            trajectory.subagent_trajectories = [*existing, *native_children]
            own_metrics = self._final_metrics(trajectory.steps)
            child_prompt = sum(
                (child.final_metrics.total_prompt_tokens or 0)
                for child in trajectory.subagent_trajectories
                if child.final_metrics
            )
            child_completion = sum(
                (child.final_metrics.total_completion_tokens or 0)
                for child in trajectory.subagent_trajectories
                if child.final_metrics
            )
            child_cached = sum(
                (child.final_metrics.total_cached_tokens or 0)
                for child in trajectory.subagent_trajectories
                if child.final_metrics
            )
            child_cost = sum(
                (child.final_metrics.total_cost_usd or 0)
                for child in trajectory.subagent_trajectories
                if child.final_metrics
            )
            trajectory.final_metrics = FinalMetrics(
                total_prompt_tokens=(own_metrics.total_prompt_tokens or 0)
                + child_prompt
                or None,
                total_completion_tokens=(own_metrics.total_completion_tokens or 0)
                + child_completion
                or None,
                total_cached_tokens=(own_metrics.total_cached_tokens or 0)
                + child_cached
                or None,
                total_cost_usd=(own_metrics.total_cost_usd or 0) + child_cost or None,
                total_steps=len(trajectory.steps),
            )
        try:
            (self.logs_dir / "trajectory.json").write_text(
                format_trajectory_json(trajectory.to_json_dict())
            )
        except OSError as exc:
            self.logger.debug(f"Failed to write Pi trajectory: {exc}")
        if trajectory.final_metrics:
            metrics = trajectory.final_metrics
            context.n_input_tokens = metrics.total_prompt_tokens or 0
            context.n_output_tokens = metrics.total_completion_tokens or 0
            context.n_cache_tokens = metrics.total_cached_tokens or 0
            context.cost_usd = metrics.total_cost_usd
