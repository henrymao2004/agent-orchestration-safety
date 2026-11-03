import copy
import json
import os
import re
import shlex
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, override

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


class OpenCode(BaseInstalledAgent):

    SUPPORTS_ATIF: bool = True
    SUPPORTS_RESUME: bool = True

    _OUTPUT_FILENAME = "opencode.txt"
    _DATABASE_RELATIVE_PATH = Path("opencode/xdg-data/opencode/opencode.db")
    CLI_FLAGS = [
        CliFlag("variant", cli="--variant", type="str"),
        CliFlag("opencode_agent", cli="--agent", type="str"),
    ]

    _DEFAULT_CONFIG: dict[str, Any] = {}

    def __init__(
        self,
        *args,
        opencode_config: dict[str, Any] | None = None,
        opencode_plugins: dict[str, str] | None = None,
        reuse_preinstalled: bool = False,
        dangerously_skip_permissions: bool = True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._opencode_config: dict[str, Any] = opencode_config or {}
        self._opencode_plugins = self._validate_plugins(opencode_plugins or {})
        self._reuse_preinstalled = reuse_preinstalled
        self._dangerously_skip_permissions = dangerously_skip_permissions
        self._instruction: str | None = None

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                OpenCode._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    @staticmethod
    def _validate_plugins(plugins: dict[str, str]) -> dict[str, str]:
        validated: dict[str, str] = {}
        for filename, source in plugins.items():
            path = Path(filename)
            if (
                not filename
                or path.name != filename
                or path.suffix not in {".js", ".ts"}
                or re.fullmatch(r"[A-Za-z0-9_.-]+", filename) is None
            ):
                raise ValueError(
                    "OpenCode plugin names must be basename-only .js or .ts files"
                )
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f"OpenCode plugin {filename!r} must have source text")
            validated[filename] = source
        return validated

    @staticmethod
    @override
    def name() -> str:
        return AgentName.OPENCODE.value

    @override
    def get_version_command(self) -> str | None:
        return ". ~/.nvm/nvm.sh; opencode --version"

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        if self._reuse_preinstalled:
            expected = shlex.quote(self._version) if self._version else ""
            version_check = (
                f'test "$(opencode --version | tail -n 1 | tr -d "\\r")" = {expected}'
                if expected
                else "opencode --version >/dev/null"
            )
            try:
                await self.exec_as_agent(
                    environment,
                    command=f"command -v opencode >/dev/null 2>&1 && {version_check}",
                )
            except NonZeroAgentExitCodeError:
                pass
            else:
                return
        await self.ensure_system_dependencies(environment, ("curl", "bash"))
        version_spec = f"@{self._version}" if self._version else "@latest"
        await self.exec_as_agent(
            environment,
            command=(
                "set -euo pipefail; "
                f"{nvm_node_install_snippet()} && "
                f"npm i -g opencode-ai{version_spec} && "
                "opencode --version"
            ),
        )

    @staticmethod
    def _millis_to_iso(timestamp_ms: int | float | None) -> str | None:
        if timestamp_ms is None:
            return None
        try:
            return datetime.fromtimestamp(
                timestamp_ms / 1000, tz=timezone.utc
            ).isoformat()
        except (OSError, ValueError, OverflowError):
            return None

    @staticmethod
    def _user_event_text(event: dict[str, Any]) -> str | None:
        parts = event.get("parts")
        if not isinstance(parts, list):
            return None
        texts = [
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        joined = "\n".join(text for text in texts if text)
        return joined or None

    def _parse_stdout(self) -> list[dict[str, Any]]:
        output_path = self.logs_dir / self._OUTPUT_FILENAME
        if not output_path.exists():
            return []

        events: list[dict[str, Any]] = []
        for line in output_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return events

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value:
            return {}
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _model_name(model: Any) -> str | None:
        model_data = OpenCode._json_object(model)
        provider = model_data.get("providerID") or model_data.get("provider_id")
        model_id = model_data.get("modelID") or model_data.get("model_id")
        if provider and model_id:
            return f"{provider}/{model_id}"
        return str(model_id) if model_id else None

    def _load_database(
        self,
    ) -> (
        tuple[
            dict[str, dict[str, Any]],
            dict[str, list[dict[str, Any]]],
        ]
        | None
    ):
        database_path = self.logs_dir / self._DATABASE_RELATIVE_PATH
        if not database_path.is_file():
            return None

        connection = sqlite3.connect(
            f"file:{database_path}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            sessions = {
                str(row["id"]): dict(row)
                for row in connection.execute("SELECT * FROM session")
            }
            messages_by_id: dict[str, dict[str, Any]] = {}
            messages_by_session: dict[str, list[dict[str, Any]]] = {}

            for row in connection.execute("SELECT * FROM message"):
                row_data = dict(row)
                message = self._json_object(row_data.get("data"))
                message.setdefault("id", row_data.get("id"))
                message.setdefault("sessionID", row_data.get("session_id"))
                message["_db_time_created"] = row_data.get("time_created")
                message["_db_time_updated"] = row_data.get("time_updated")
                message["_parts"] = []
                message_id = str(row_data["id"])
                session_id = str(row_data["session_id"])
                messages_by_id[message_id] = message
                messages_by_session.setdefault(session_id, []).append(message)

            for row in connection.execute("SELECT * FROM part"):
                row_data = dict(row)
                message = messages_by_id.get(str(row_data.get("message_id")))
                if message is None:
                    continue
                part = self._json_object(row_data.get("data"))
                part.setdefault("id", row_data.get("id"))
                part.setdefault("messageID", row_data.get("message_id"))
                part.setdefault("sessionID", row_data.get("session_id"))
                part["_db_time_created"] = row_data.get("time_created")
                part["_db_time_updated"] = row_data.get("time_updated")
                message["_parts"].append(part)

            def sort_key(item: dict[str, Any]) -> tuple[int, str]:
                return (
                    int(item.get("_db_time_created") or 0),
                    str(item.get("id") or ""),
                )

            for messages in messages_by_session.values():
                messages.sort(key=sort_key)
                for message in messages:
                    message["_parts"].sort(key=sort_key)

            return sessions, messages_by_session
        finally:
            connection.close()

    @staticmethod
    def _message_timestamp(message: dict[str, Any]) -> int | float | None:
        time_data = message.get("time")
        if isinstance(time_data, dict):
            created = time_data.get("created")
            if created is not None:
                return created
        return message.get("_db_time_created")

    @staticmethod
    def _part_timestamp(part: dict[str, Any]) -> int | float | None:
        time_data = part.get("time")
        if isinstance(time_data, dict):
            started = time_data.get("start")
            if started is not None:
                return started
        state = part.get("state")
        if isinstance(state, dict):
            state_time = state.get("time")
            if isinstance(state_time, dict) and state_time.get("start") is not None:
                return state_time["start"]
        return part.get("_db_time_created")

    def _database_assistant_step(
        self,
        session_id: str,
        message: dict[str, Any],
        parts: list[dict[str, Any]],
        direct_children: dict[str, Trajectory],
        step_id: int,
    ) -> Step | None:
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        observation_results: list[ObservationResult] = []
        finish: dict[str, Any] | None = None

        for part in parts:
            part_type = part.get("type")
            if part_type == "text":
                text_value = part.get("text")
                if text_value:
                    text_parts.append(str(text_value))
                continue
            if part_type == "reasoning":
                reasoning = part.get("text")
                if reasoning:
                    reasoning_parts.append(str(reasoning))
                continue
            if part_type == "step-finish":
                finish = part
                continue
            if part_type != "tool":
                continue

            state = part.get("state")
            state = state if isinstance(state, dict) else {}
            tool_input = state.get("input")
            if not isinstance(tool_input, dict):
                tool_input = {"value": tool_input} if tool_input is not None else {}
            call_id = str(part.get("callID") or part.get("id") or "")
            tool_name = str(part.get("tool") or "")
            status = str(state.get("status") or "unknown")
            state_metadata = state.get("metadata")
            state_metadata = state_metadata if isinstance(state_metadata, dict) else {}
            call_extra: dict[str, Any] = {
                "status": status,
                "opencode_part_id": part.get("id"),
            }
            if isinstance(state.get("time"), dict):
                call_extra["time"] = state["time"]
            tool_calls.append(
                ToolCall(
                    tool_call_id=call_id,
                    function_name=tool_name,
                    arguments=tool_input,
                    extra=call_extra,
                )
            )

            content: str | None = None
            if state.get("output") is not None:
                content = str(state["output"])
            elif state.get("error") is not None:
                content = str(state["error"])

            refs: list[SubagentTrajectoryRef] = []
            if tool_name == "task":
                child_session_id = state_metadata.get("sessionId")
                child = direct_children.get(str(child_session_id))
                if child is not None:
                    refs.append(
                        SubagentTrajectoryRef(
                            trajectory_id=child.trajectory_id,
                            session_id=child.session_id,
                            extra={
                                "parent_session_id": session_id,
                                "opencode_part_id": part.get("id"),
                            },
                        )
                    )

            result_extra: dict[str, Any] = {"tool_status": status}
            if state_metadata:
                result_extra["opencode_metadata"] = state_metadata
            if content is not None or refs:
                observation_results.append(
                    ObservationResult(
                        source_call_id=call_id or None,
                        content=content,
                        subagent_trajectory_ref=refs or None,
                        extra=result_extra,
                    )
                )

        if not (text_parts or reasoning_parts or tool_calls or finish):
            return None

        finish_data = finish or {}
        tokens = finish_data.get("tokens")
        if not isinstance(tokens, dict):
            tokens = message.get("tokens")
        tokens = tokens if isinstance(tokens, dict) else {}
        cache = tokens.get("cache")
        cache = cache if isinstance(cache, dict) else {}
        input_tokens = int(tokens.get("input") or 0)
        output_tokens = int(tokens.get("output") or 0)
        cache_read = int(cache.get("read") or 0)
        cache_write = int(cache.get("write") or 0)
        reasoning_tokens = int(tokens.get("reasoning") or 0)
        cost = finish_data.get("cost")
        if cost is None:
            cost = message.get("cost")
        cost = float(cost or 0)
        metrics = None
        if input_tokens or output_tokens or cache_read or cost:
            metrics = Metrics(
                prompt_tokens=input_tokens + cache_read,
                completion_tokens=output_tokens,
                cached_tokens=cache_read or None,
                cost_usd=cost or None,
                extra={
                    key: value
                    for key, value in {
                        "reasoning_tokens": reasoning_tokens,
                        "cache_write_tokens": cache_write,
                    }.items()
                    if value
                }
                or None,
            )

        timestamp_source = next(
            (
                self._part_timestamp(part)
                for part in parts
                if part.get("type") == "step-start"
            ),
            self._message_timestamp(message),
        )
        model_name = self._model_name(
            {
                "providerID": message.get("providerID"),
                "modelID": message.get("modelID"),
            }
        )
        step_extra: dict[str, Any] = {
            "opencode_message_id": message.get("id"),
            "opencode_agent": message.get("agent"),
        }
        finish_reason = finish_data.get("reason") or message.get("finish")
        if finish_reason:
            step_extra["finish_reason"] = finish_reason

        return Step(
            step_id=step_id,
            timestamp=self._millis_to_iso(timestamp_source),
            source="agent",
            message="\n".join(text_parts),
            reasoning_content="\n\n".join(reasoning_parts) or None,
            model_name=model_name,
            tool_calls=tool_calls or None,
            observation=(
                Observation(results=observation_results)
                if observation_results
                else None
            ),
            metrics=metrics,
            llm_call_count=1,
            extra={
                key: value for key, value in step_extra.items() if value is not None
            },
        )

    def _database_session_steps(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        direct_children: dict[str, Trajectory],
    ) -> list[Step]:
        steps: list[Step] = []
        for message in messages:
            parts = message.get("_parts")
            parts = parts if isinstance(parts, list) else []
            if message.get("role") == "user":
                texts = [
                    str(part.get("text"))
                    for part in parts
                    if part.get("type") == "text" and part.get("text")
                ]
                if not texts:
                    continue
                steps.append(
                    Step(
                        step_id=len(steps) + 1,
                        timestamp=self._millis_to_iso(self._message_timestamp(message)),
                        source="user",
                        message="\n".join(texts),
                        extra={"opencode_message_id": message.get("id")},
                    )
                )
                continue
            if message.get("role") != "assistant":
                continue

            groups: list[list[dict[str, Any]]] = []
            current: list[dict[str, Any]] = []
            for part in parts:
                if part.get("type") == "step-start" and current:
                    groups.append(current)
                    current = []
                current.append(part)
                if part.get("type") == "step-finish":
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)

            for group in groups:
                step = self._database_assistant_step(
                    session_id,
                    message,
                    group,
                    direct_children,
                    len(steps) + 1,
                )
                if step is not None:
                    steps.append(step)
        return steps

    @staticmethod
    def _final_metrics(steps: list[Step]) -> FinalMetrics:
        total_prompt = 0
        total_completion = 0
        total_cached = 0
        total_cost = 0.0
        for step in steps:
            if step.metrics is None:
                continue
            total_prompt += step.metrics.prompt_tokens or 0
            total_completion += step.metrics.completion_tokens or 0
            total_cached += step.metrics.cached_tokens or 0
            total_cost += step.metrics.cost_usd or 0
        return FinalMetrics(
            total_prompt_tokens=total_prompt or None,
            total_completion_tokens=total_completion or None,
            total_cached_tokens=total_cached or None,
            total_cost_usd=total_cost or None,
            total_steps=len(steps),
        )

    def _convert_database_to_trajectory(
        self, events: list[dict[str, Any]]
    ) -> Trajectory | None:
        loaded = self._load_database()
        if loaded is None:
            return None
        sessions, messages_by_session = loaded
        if not sessions:
            return None

        root_session_id = next(
            (
                str(event["sessionID"])
                for event in events
                if event.get("sessionID") in sessions
            ),
            None,
        )
        if root_session_id is None:
            root_candidates = [
                session for session in sessions.values() if not session.get("parent_id")
            ]
            if not root_candidates:
                return None
            root = max(
                root_candidates,
                key=lambda item: (
                    int(item.get("time_updated") or item.get("time_created") or 0),
                    str(item.get("id") or ""),
                ),
            )
            root_session_id = str(root["id"])

        children_by_parent: dict[str, list[str]] = {}
        for session_id, session in sessions.items():
            parent_id = session.get("parent_id")
            if parent_id:
                children_by_parent.setdefault(str(parent_id), []).append(session_id)
        for child_ids in children_by_parent.values():
            child_ids.sort(
                key=lambda child_id: (
                    int(sessions[child_id].get("time_created") or 0),
                    child_id,
                )
            )

        building: set[str] = set()

        def build(session_id: str) -> Trajectory | None:
            if session_id in building:
                raise ValueError(f"Cycle in OpenCode session tree at {session_id}")
            session = sessions.get(session_id)
            if session is None:
                return None
            building.add(session_id)
            try:
                child_trajectories = [
                    child
                    for child_id in children_by_parent.get(session_id, [])
                    if (child := build(child_id)) is not None
                ]
                direct_children = {
                    str(child.session_id): child
                    for child in child_trajectories
                    if child.session_id is not None
                }
                steps = self._database_session_steps(
                    session_id,
                    messages_by_session.get(session_id, []),
                    direct_children,
                )
                if not steps:
                    return None

                model_name = self._model_name(session.get("model"))
                if model_name is None:
                    model_name = next(
                        (
                            step.model_name
                            for step in steps
                            if step.model_name is not None
                        ),
                        self.model_name,
                    )
                profile = session.get("agent")
                return Trajectory(
                    schema_version="ATIF-v1.7",
                    session_id=session_id,
                    trajectory_id=f"opencode:{session_id}",
                    agent=Agent(
                        name=str(profile or "opencode"),
                        version=str(
                            session.get("version") or self.version() or "unknown"
                        ),
                        model_name=model_name,
                        extra={
                            "framework": "opencode",
                            "agent_profile": profile,
                            "parent_session_id": session.get("parent_id"),
                        },
                    ),
                    steps=steps,
                    final_metrics=self._final_metrics(steps),
                    subagent_trajectories=child_trajectories or None,
                )
            finally:
                building.remove(session_id)

        return build(root_session_id)

    def _error_messages(self) -> list[str]:
        messages: list[str] = []
        for event in self._parse_stdout():
            if event.get("type") != "error":
                continue
            error = event.get("error")
            if isinstance(error, dict):
                data = error.get("data")
                message = data.get("message") if isinstance(data, dict) else None
                messages.append(str(message or error.get("name") or error))
            else:
                messages.append(str(error))
        return messages

    def _convert_events_to_trajectory(
        self, events: list[dict[str, Any]]
    ) -> Trajectory | None:
        if not events:
            return None

        session_id: str | None = None
        for event in events:
            sid = event.get("sessionID")
            if sid:
                session_id = sid
                break

        turns: list[dict[str, Any]] = []
        current_turn: dict[str, Any] | None = None
        user_message: str | None = None
        user_timestamp: int | None = None

        for event in events:
            etype = event.get("type")

            if etype == "user":
                if user_message is None:
                    user_message = self._user_event_text(event)
                    user_timestamp = event.get("timestamp")
                continue

            if etype == "step_start":
                current_turn = {
                    "parts": [],
                    "finish": None,
                    "timestamp": event.get("timestamp"),
                }
                continue

            if etype == "step_finish":
                if current_turn is not None:
                    current_turn["finish"] = event.get("part", {})
                    turns.append(current_turn)
                    current_turn = None
                continue

            if current_turn is not None and etype in ("text", "reasoning", "tool_use"):
                current_turn["parts"].append(event.get("part", {}))

        steps: list[Step] = []
        step_id = 1
        total_cost = 0.0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read = 0

        for turn in turns:
            text_parts: list[str] = []
            reasoning_parts: list[str] = []
            tool_calls_list: list[ToolCall] = []
            observation_results: list[ObservationResult] = []
            timestamp = self._millis_to_iso(turn.get("timestamp"))

            for part in turn["parts"]:
                ptype = part.get("type")

                if ptype == "text":
                    text = part.get("text", "")
                    if text:
                        text_parts.append(text)

                elif ptype == "reasoning":
                    reasoning = part.get("text", "")
                    if reasoning:
                        reasoning_parts.append(reasoning)

                elif ptype == "tool":
                    state = part.get("state", {})
                    tool_name = part.get("tool", "")
                    tool_input = state.get("input", {})
                    tool_output = state.get("output")
                    call_id = part.get("callID", part.get("id", ""))

                    if not isinstance(tool_input, dict):
                        tool_input = {"value": tool_input} if tool_input else {}

                    tool_calls_list.append(
                        ToolCall(
                            tool_call_id=call_id,
                            function_name=tool_name,
                            arguments=tool_input,
                        )
                    )

                    if tool_output is not None:
                        observation_results.append(
                            ObservationResult(
                                source_call_id=call_id or None,
                                content=str(tool_output),
                            )
                        )

            finish = turn.get("finish", {})
            tokens = finish.get("tokens", {})
            cost = finish.get("cost", 0) or 0
            input_tok = tokens.get("input", 0) or 0
            output_tok = tokens.get("output", 0) or 0
            reasoning_tok = tokens.get("reasoning", 0) or 0
            cache = tokens.get("cache", {})
            cache_read = cache.get("read", 0) or 0
            cache_write = cache.get("write", 0) or 0

            total_cost += cost
            total_input_tokens += input_tok + cache_read
            total_output_tokens += output_tok
            total_cache_read += cache_read

            metrics: Metrics | None = None
            if input_tok or output_tok or cache_read:
                metrics = Metrics(
                    prompt_tokens=input_tok + cache_read,
                    completion_tokens=output_tok,
                    cached_tokens=cache_read if cache_read else None,
                    cost_usd=cost if cost else None,
                    extra={
                        k: v
                        for k, v in {
                            "reasoning_tokens": reasoning_tok,
                            "cache_write_tokens": cache_write,
                        }.items()
                        if v
                    }
                    or None,
                )

            message_text = "\n".join(text_parts) if text_parts else ""
            observation = (
                Observation(results=observation_results)
                if observation_results
                else None
            )

            step_kwargs: dict[str, Any] = {
                "step_id": step_id,
                "timestamp": timestamp,
                "source": "agent",
                "message": message_text,
                "model_name": self.model_name,
                "llm_call_count": 1,
            }
            if reasoning_parts:
                step_kwargs["reasoning_content"] = "\n\n".join(reasoning_parts)
            if tool_calls_list:
                step_kwargs["tool_calls"] = tool_calls_list
            if observation:
                step_kwargs["observation"] = observation
            if metrics:
                step_kwargs["metrics"] = metrics

            steps.append(Step(**step_kwargs))
            step_id += 1

        if not steps:
            return None

        user_text = user_message or self._instruction
        if user_text and not any(step.source == "user" for step in steps):
            steps.insert(
                0,
                Step(
                    step_id=1,
                    timestamp=self._millis_to_iso(user_timestamp),
                    source="user",
                    message=user_text,
                ),
            )
            for index, step in enumerate(steps, start=1):
                step.step_id = index

        final_metrics = FinalMetrics(
            total_prompt_tokens=total_input_tokens or None,
            total_completion_tokens=total_output_tokens or None,
            total_cached_tokens=total_cache_read or None,
            total_cost_usd=total_cost if total_cost else None,
            total_steps=len(steps),
        )

        return Trajectory(
            schema_version="ATIF-v1.7",
            session_id=session_id or "unknown",
            agent=Agent(
                name="opencode",
                version=self.version() or "unknown",
                model_name=self.model_name,
            ),
            steps=steps,
            final_metrics=final_metrics,
        )

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        events = self._parse_stdout()
        trajectory: Trajectory | None = None
        try:
            trajectory = self._convert_database_to_trajectory(events)
        except Exception:
            self.logger.exception("Failed to convert opencode database to trajectory")

        if trajectory is None and events:
            try:
                trajectory = self._convert_events_to_trajectory(events)
            except Exception:
                self.logger.exception("Failed to convert opencode events to trajectory")
                return

        if not trajectory:
            return

        trajectory_path = self.logs_dir / "trajectory.json"
        try:
            trajectory_path.write_text(
                format_trajectory_json(trajectory.to_json_dict())
            )
            self.logger.debug(f"Wrote opencode trajectory to {trajectory_path}")
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
            f"mkdir -p ~/.config/opencode/skills && "
            f"cp -r {shlex.quote(self.skills_dir)}/* "
            f"~/.config/opencode/skills/ 2>/dev/null || true"
        )

    def _build_register_plugins_command(self) -> str | None:
        if not self._opencode_plugins:
            return None
        commands = ["mkdir -p ~/.config/opencode/plugins"]
        for filename, source in sorted(self._opencode_plugins.items()):
            destination = f"~/.config/opencode/plugins/{filename}"
            commands.append(f"printf %s {shlex.quote(source)} > {destination}")
        return " && ".join(commands)

    def _build_register_config_command(self) -> str | None:
        config: dict[str, Any] = {}

        if self.mcp_servers:
            mcp: dict[str, dict[str, Any]] = {}
            for server in self.mcp_servers:
                if server.transport == "stdio":
                    cmd_list = [server.command] + server.args if server.command else []
                    mcp[server.name] = {"type": "local", "command": cmd_list}
                else:
                    mcp[server.name] = {"type": "remote", "url": server.url}
            config["mcp"] = mcp

        if self.model_name and "/" in self.model_name:
            provider, model_id = self.model_name.split("/", 1)
            provider_config: dict[str, Any] = {"models": {model_id: {}}}
            base_url = None
            if provider == "openai":
                base_url = os.environ.get("OPENAI_BASE_URL")
            elif provider == "anthropic":
                base_url = os.environ.get("ANTHROPIC_BASE_URL")
            if base_url:
                provider_config.setdefault("options", {})["baseURL"] = base_url
            config["provider"] = {provider: provider_config}

        config = self._deep_merge(copy.deepcopy(self._DEFAULT_CONFIG), config)
        config = self._deep_merge(config, self._opencode_config)

        if not config:
            return None

        config_json = json.dumps(config, indent=2)
        escaped = shlex.quote(config_json)
        return f"mkdir -p ~/.config/opencode && echo {escaped} > ~/.config/opencode/opencode.json"

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

        provider, _ = self.model_name.split("/", 1)

        env = dict(self._extra_env)
        keys = []

        if provider == "amazon-bedrock":
            keys.extend(["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"])
        elif provider == "anthropic":
            keys.extend(["ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"])
        elif provider == "azure":
            keys.extend(["AZURE_RESOURCE_NAME", "AZURE_API_KEY"])
        elif provider == "deepseek":
            keys.append("DEEPSEEK_API_KEY")
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
        elif provider == "llama":
            keys.append("LLAMA_API_KEY")
        elif provider == "mistral":
            keys.append("MISTRAL_API_KEY")
        elif provider == "openai":
            keys.append("OPENAI_API_KEY")
            keys.append("OPENAI_BASE_URL")
        elif provider == "opencode":
            keys.append("OPENCODE_API_KEY")
        elif provider == "xai":
            keys.append("XAI_API_KEY")
        elif provider == "openrouter":
            keys.append("OPENROUTER_API_KEY")

        for key in keys:
            if value := self._get_env(key):
                env[key] = value

        env["OPENCODE_FAKE_VCS"] = "git"
        env["XDG_DATA_HOME"] = "/logs/agent/opencode/xdg-data"
        env["XDG_STATE_HOME"] = "/logs/agent/opencode/xdg-state"

        skills_command = self._build_register_skills_command()
        if skills_command:
            await self.exec_as_agent(environment, command=skills_command, env=env)

        plugins_command = self._build_register_plugins_command()
        if plugins_command:
            await self.exec_as_agent(environment, command=plugins_command, env=env)

        mcp_command = self._build_register_config_command()
        if mcp_command:
            await self.exec_as_agent(environment, command=mcp_command, env=env)

        cli_flags = self.build_cli_flags()
        cli_flags_arg = (cli_flags + " ") if cli_flags else ""
        resume_flag = "--continue " if self._resume else ""
        permission_flag = (
            "--dangerously-skip-permissions "
            if self._dangerously_skip_permissions
            else ""
        )

        await self.exec_as_agent(
            environment,
            command=(
                ". ~/.nvm/nvm.sh; "
                f"opencode --model={self.model_name} run --format=json "
                f"{resume_flag}{cli_flags_arg}--thinking "
                f"{permission_flag}-- {escaped_instruction} "
                f"2>&1 </dev/null | stdbuf -oL tee /logs/agent/opencode.txt"
            ),
            env=env,
        )

        if messages := self._error_messages():
            raise NonZeroAgentExitCodeError(
                "OpenCode emitted error event(s): " + "; ".join(messages[:3])
            )
