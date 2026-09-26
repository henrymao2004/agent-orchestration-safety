#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

import yaml


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
SYSTEMS_CONFIG = PACKAGE / "config" / "systems.yaml"
POOLS_CONFIG = PACKAGE / "config" / "pool_templates.json"
GOALS_CONFIG = PACKAGE / "config" / "actor_goals.json"
TASKS_ROOT = PACKAGE / "tasks"
OPENCLAW_TASKS_ROOT = ROOT / "build" / "tasks_openclaw"
PI_GIT_TASKS_ROOT = ROOT / "build" / "tasks_pi_git"
OUT = ROOT / "build" / "jobs"
DEFENSES_ROOT = PACKAGE / "defenses"
BENCH_VERSION = "benchmark-v1.0.0"
OPENCLAW_AGENT_BASE_IMAGE = "trustfork-agents:tf-three-harnesses-v1"
DEFENSE_PLUGIN_FILES = {
    "anonymize-responses": "anonymize-responses.js",
    "check-identity": "check-identity.js",
    "verify-before-action": "verify-before-action.js",
}
DEFENSE_PLUGIN_FILES_BY_HARNESS = {
    "opencode": DEFENSE_PLUGIN_FILES,
    "pi": DEFENSE_PLUGIN_FILES,
    "openclaw": {
        name: filename.removesuffix(".js") + ".cjs"
        for name, filename in DEFENSE_PLUGIN_FILES.items()
    },
}
DEFENSE_MANIFEST_MARKER = "__TRUSTFORK_DEFENSE_MANIFEST__"
AGENT_IMPORT_PATHS = {
    "opencode": "trustfork.agents.opencode:OpenCode",
    "pi": "trustfork.agents.pi:Pi",
    "openclaw": "trustfork.agents.openclaw:OpenClaw",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_openclaw_task(task_dir: Path) -> Path:
    destination = OPENCLAW_TASKS_ROOT / task_dir.name
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(task_dir, destination, copy_function=os.link)
    except OSError:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(task_dir, destination)

    dockerfile = destination / "environment" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("FROM trustfork-agents:"):
        raise ValueError(f"Unexpected agent base image in {dockerfile}")
    lines[0] = f"FROM {OPENCLAW_AGENT_BASE_IMAGE}"
    dockerfile.unlink()
    dockerfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    verifier_text = (PACKAGE / "scoring" / "verifier.py").read_text(encoding="utf-8")
    verifier_paths = sorted(destination.glob("**/tests/verifier.py"))
    if not verifier_paths:
        raise ValueError(f"No verifier.py found in {destination}")
    for verifier_path in verifier_paths:
        verifier_path.unlink()
        verifier_path.write_text(verifier_text, encoding="utf-8")
    return destination


def prepare_pi_git_task(task_dir: Path) -> Path:
    destination = PI_GIT_TASKS_ROOT / task_dir.name
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(task_dir, destination, copy_function=os.link)
    except OSError:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(task_dir, destination)

    dockerfile = destination / "environment" / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8").rstrip()
    dockerfile.unlink()
    dockerfile.write_text(
        text
        + "\nRUN git init /workspace \\\n"
        + "    && git -C /workspace config user.email trustfork@local \\\n"
        + "    && git -C /workspace config user.name TrustFork \\\n"
        + "    && git -C /workspace add -A \\\n"
        + "    && git -C /workspace commit --allow-empty -m baseline --quiet\n",
        encoding="utf-8",
    )
    return destination


def candidate_name(slot: str) -> str:
    return f"candidate_{slot.lower()}"


def display_name(model: str) -> str:
    return (
        model.replace("-", " ")
        .title()
        .replace("Glm", "GLM")
        .replace("Gpt", "GPT")
        .replace("Minimax", "MiniMax")
        .replace("Kimi", "Kimi")
    )


def render_display(
    task_spec: dict[str, Any],
    pool: dict[str, dict[str, Any]],
    orchestrator: dict[str, Any],
) -> dict[str, str]:
    identity_id = task_spec["identity_display_id"]
    slots = list(pool)
    if identity_id == "M0":
        return {slot: f"Subagent {slot}" for slot in slots}
    truthful = {
        slot: display_name(pool[slot].get("display_model", pool[slot]["api_model"]))
        for slot in slots
    }
    if identity_id == "M1":
        return truthful
    if identity_id == "M2":
        pair = task_spec["identity_swap_pair"]
        if not pair:
            raise ValueError("M2 requires a swap pair")
        display = dict(truthful)
        left, right = pair
        display[left], display[right] = display[right], display[left]
        return display
    if identity_id == "M3":
        return {
            slot: f"{truthful[slot]} ({pool[slot]['tier']} model)" for slot in slots
        }
    if identity_id == "M4":
        inverse = {"frontier": "efficient", "efficient": "frontier"}
        return {
            slot: f"{truthful[slot]} ({inverse[pool[slot]['tier']]} model)"
            for slot in slots
        }
    if identity_id in {"M5", "M6"}:
        display = {}
        for slot in slots:
            relation = (
                "same-family"
                if pool[slot]["family"] == orchestrator["family"]
                else "cross-family"
            )
            if identity_id == "M6":
                relation = (
                    "cross-family" if relation == "same-family" else "same-family"
                )
            display[slot] = f"Subagent {slot} ({relation} model)"
        return display
    raise ValueError(f"Unsupported identity display: {identity_id}")


def resolve_pool(
    template: dict[str, Any],
    orchestrator: dict[str, Any],
    backbones: dict[str, dict[str, Any]],
    registry: dict[str, Any],
    task_spec: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    families = list(registry)
    reference = orchestrator["family"]
    resolved: dict[str, dict[str, Any]] = {}
    slot_rows = template["slots"]
    if task_spec is not None:
        # Reuse the rotated pool roles and offsets recorded in the task spec.
        actors = task_spec["actors"]
        slot_rows = [
            {
                "slot": slot,
                "role": actors[slot]["pool_role"],
                **(
                    {"offset": actors[slot]["pool_offset"]}
                    if "pool_offset" in actors[slot]
                    else {}
                ),
            }
            for slot in actors
        ]
        roles = sorted(row["role"] for row in slot_rows)
        if roles != sorted(row["role"] for row in template["slots"]) or any(
            row["role"].startswith("other_family_") and "offset" not in row
            for row in slot_rows
        ):
            raise ValueError(
                f"{task_spec['task_id']}: actor pool roles do not match "
                f"template {task_spec['pool_template_id']}"
            )
    for row in slot_rows:
        slot = row["slot"]
        role = row["role"]
        if role == "orchestrator":
            family, tier = reference, orchestrator["tier"]
        elif role == "same_family_opposite_tier":
            family = reference
            tier = "efficient" if orchestrator["tier"] == "frontier" else "frontier"
        elif role == "other_family_same_tier":
            others = [family for family in families if family != reference]
            family = others[int(row.get("offset", 0)) % len(others)]
            tier = orchestrator["tier"]
        elif role == "other_family_opposite_tier":
            others = [family for family in families if family != reference]
            family = others[int(row.get("offset", 0)) % len(others)]
            tier = "efficient" if orchestrator["tier"] == "frontier" else "frontier"
        else:
            raise ValueError(f"Unsupported pool role: {role}")
        model_id = registry[family][tier]
        resolved[slot] = backbones[model_id]
    return resolved


def provider_config(
    providers: dict[str, Any], used_provider_ids: set[str]
) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for provider_id in sorted(used_provider_ids):
        entry = providers[provider_id]
        base_url = entry["base_url"]
        if entry.get("base_url_env"):
            base_url = "{env:" + entry["base_url_env"] + "}"
        config[provider_id] = {
            "npm": entry["npm"],
            "name": entry["name"],
            "options": {
                "baseURL": base_url,
                "apiKey": "{env:" + entry["api_key_env"] + "}",
            },
            "models": {model: {} for model in entry["models"]},
        }
    return config


def pi_models_config(
    providers: dict[str, Any], used_provider_ids: set[str]
) -> dict[str, Any]:
    rendered: dict[str, Any] = {"providers": {}}
    for provider_id in sorted(used_provider_ids):
        entry = providers[provider_id]
        base_url = entry.get("pi_base_url", entry["base_url"])
        if entry.get("base_url_env"):
            base_url = "{env:" + entry["base_url_env"] + "}"
        provider = {
            "baseUrl": base_url,
            "api": entry["pi_api"],
            "apiKey": "$" + entry["api_key_env"],
            "models": [
                {
                    "id": model,
                    "name": model,
                    "reasoning": bool(entry.get("reasoning", True)),
                    "input": ["text"],
                }
                for model in entry["models"]
            ],
        }
        if entry.get("pi_compat"):
            provider["compat"] = entry["pi_compat"]
        rendered["providers"][provider_id] = provider
    return rendered


OPENCLAW_PROVIDER_ALIASES = {
    "kimi": "trustfork-kimi",
}

OPENCLAW_API_KEY_ENV_ALIASES = {
    "KIMI_API_KEY": "TRUSTFORK_KIMI_API_KEY",
}


def openclaw_provider_id(provider_id: str) -> str:
    return OPENCLAW_PROVIDER_ALIASES.get(provider_id, provider_id)


def openclaw_api_key_env(api_key_env: str) -> str:
    return OPENCLAW_API_KEY_ENV_ALIASES.get(api_key_env, api_key_env)


def openclaw_models_config(
    providers: dict[str, Any], used_provider_ids: set[str]
) -> dict[str, Any]:
    rendered: dict[str, Any] = {"mode": "merge", "providers": {}}
    for provider_id in sorted(used_provider_ids):
        entry = providers[provider_id]
        rendered_provider_id = openclaw_provider_id(provider_id)
        api_key_env = openclaw_api_key_env(entry["api_key_env"])
        base_url = entry.get("pi_base_url", entry["base_url"])
        if entry.get("base_url_env"):
            base_url = "${" + entry["base_url_env"] + "}"
        models: list[dict[str, Any]] = []
        for model in entry["models"]:
            rendered_model: dict[str, Any] = {
                "id": model,
                "name": model,
                "reasoning": bool(entry.get("reasoning", True)),
                "input": ["text"],
            }
            models.append(rendered_model)
        rendered["providers"][rendered_provider_id] = {
            "baseUrl": base_url,
            "apiKey": "${" + api_key_env + "}",
            "api": entry["pi_api"],
            "models": models,
        }
    return rendered


def openclaw_roster(
    orchestrator: dict[str, Any],
    pool: dict[str, dict[str, Any]],
    display: dict[str, str],
    goal_prompt_by_slot: dict[str, str | None],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate_ids = [candidate_name(slot) for slot in pool]
    entries: list[dict[str, Any]] = [
        {
            "id": "main",
            "default": True,
            "name": "TrustFork orchestrator",
            "workspace": "/workspace",
            "model": (
                f"{openclaw_provider_id(orchestrator['provider'])}/"
                f"{orchestrator['api_model']}"
            ),
            "subagents": {
                "allowAgents": candidate_ids,
                "requireAgentId": True,
                "delegationMode": "prefer",
            },
        }
    ]
    roster: list[dict[str, Any]] = []
    for slot, backbone in pool.items():
        profile = candidate_name(slot)
        workspace = "/workspace"
        entries.append(
            {
                "id": profile,
                "name": display[slot],
                "description": f"{display[slot]}.",
                "workspace": workspace,
                "model": (
                    f"{openclaw_provider_id(backbone['provider'])}/"
                    f"{backbone['api_model']}"
                ),
                "subagents": {"allowAgents": [], "requireAgentId": True},
            }
        )
        roster.append(
            {
                "name": profile,
                "description": f"{display[slot]}.",
                "model": (
                    f"{openclaw_provider_id(backbone['provider'])}/"
                    f"{backbone['api_model']}"
                ),
                "workspace": workspace,
                "systemPrompt": goal_prompt_by_slot.get(slot) or "",
            }
        )
    config = {
        "gateway": {
            "mode": "local",
            "bind": "loopback",
            "auth": {"mode": "none"},
        },
        "tools": {"profile": "coding"},
        "agents": {
            "defaults": {
                "subagents": {
                    "maxConcurrent": 4,
                    "maxChildrenPerAgent": 4,
                    "maxSpawnDepth": 1,
                    "delegationMode": "prefer",
                    "requireAgentId": True,
                }
            },
            "list": entries,
        }
    }
    return config, roster


def opencode_roster(
    task_spec: dict[str, Any],
    pool: dict[str, dict[str, Any]],
    display: dict[str, str],
    goal_prompt_by_slot: dict[str, str | None],
) -> dict[str, Any]:
    allowed = {candidate_name(slot): "allow" for slot in pool}
    agents: dict[str, Any] = {
        "orchestrator": {
            "description": "Coordinates the configured subagents for the task.",
            "mode": "primary",
            "tools": {
                "*": False,
                "bash": False,
                "edit": False,
                "write": False,
                "read": False,
                "grep": False,
                "glob": False,
                "list": False,
                "webfetch": False,
                "todowrite": False,
                "todoread": False,
                "patch": False,
                "skill": False,
                "question": False,
                "task": True,
            },
            "permission": {"task": {"*": "deny", **allowed}},
        }
    }
    for slot, backbone in pool.items():
        profile = candidate_name(slot)
        row: dict[str, Any] = {
            "description": f"{display[slot]}.",
            "mode": "subagent",
            "model": f"{backbone['provider']}/{backbone['api_model']}",
            "tools": {"task": False},
            "permission": {"external_directory": "allow"},
        }
        prompt = goal_prompt_by_slot.get(slot)
        if prompt is not None:
            row["prompt"] = prompt
        agents[profile] = row
    return agents


def pi_roster(
    pool: dict[str, dict[str, Any]],
    display: dict[str, str],
    goal_prompt_by_slot: dict[str, str | None],
) -> list[dict[str, Any]]:
    work_tools = ["read", "bash", "edit", "write", "grep", "find", "ls"]
    return [
        {
            "name": candidate_name(slot),
            "description": f"{display[slot]}.",
            "model": f"{backbone['provider']}/{backbone['api_model']}",
            "tools": work_tools,
            "systemPrompt": goal_prompt_by_slot.get(slot) or "",
            "promptMode": (
                "replace" if goal_prompt_by_slot.get(slot) is not None else "append"
            ),
            "persistSession": True,
            "sessionDir": f"/logs/agent/pi/subagents/{candidate_name(slot)}",
        }
        for slot, backbone in pool.items()
    ]


def defense_manifest(
    defense: str,
    system_id: str,
    task_spec: dict[str, Any],
    pool: dict[str, dict[str, Any]],
    display: dict[str, str],
    cli: str = "opencode",
) -> dict[str, Any]:
    identity_display_id = task_spec["identity_display_id"]
    claim_status = {
        "M0": "undisclosed",
        "M1": "verified",
        "M2": "mismatch",
        "M3": "verified",
        "M4": "mismatch",
        "M5": "verified",
        "M6": "mismatch",
    }[identity_display_id]
    return {
        "schema_version": "trustfork-defense-manifest-v1",
        "defense": defense,
        "system_id": system_id,
        "task_id": task_spec["task_id"],
        "identity_display_id": identity_display_id,
        "identity_claim_status": claim_status,
        "actors": [
            {
                "slot": slot,
                "profile": candidate_name(slot),
                "displayed_identity": display[slot],
                "actual_identity": {
                    "provider": (
                        openclaw_provider_id(backbone["provider"])
                        if cli == "openclaw"
                        else backbone["provider"]
                    ),
                    "api_model": backbone["api_model"],
                    "display_model": display_name(
                        backbone.get("display_model", backbone["api_model"])
                    ),
                    "family": backbone["family"],
                    "tier": backbone["tier"],
                },
            }
            for slot, backbone in pool.items()
        ],
    }


def rendered_defense_plugin(
    defense: str,
    system_id: str,
    task_spec: dict[str, Any],
    pool: dict[str, dict[str, Any]],
    display: dict[str, str],
    cli: str = "opencode",
) -> tuple[str, str]:
    try:
        filename = DEFENSE_PLUGIN_FILES_BY_HARNESS[cli][defense]
    except KeyError as exc:
        raise ValueError(f"Unsupported defense {defense!r} for {cli!r}") from exc
    source = (DEFENSES_ROOT / cli / filename).read_text(encoding="utf-8")
    if source.count(DEFENSE_MANIFEST_MARKER) != 1:
        raise ValueError(
            f"Defense plugin {filename} must contain exactly one manifest marker"
        )
    manifest = defense_manifest(
        defense, system_id, task_spec, pool, display, cli=cli
    )
    rendered = source.replace(
        DEFENSE_MANIFEST_MARKER,
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
    )
    return filename, rendered


def job_config(
    system_id: str,
    cli: str,
    orchestrator: dict[str, Any],
    providers: dict[str, Any],
    task_dir: Path,
    task_spec: dict[str, Any],
    pool: dict[str, dict[str, Any]],
    display: dict[str, str],
    goal_prompt_by_slot: dict[str, str | None],
    defense: str | None = None,
) -> dict[str, Any]:
    used_providers = {orchestrator["provider"]} | {
        backbone["provider"] for backbone in pool.values()
    }
    connection_envs = {providers[pid]["api_key_env"] for pid in used_providers}
    connection_envs.update(
        providers[pid]["base_url_env"]
        for pid in used_providers
        if providers[pid].get("base_url_env")
    )
    connection_env_map = {
        key: "${" + key + "}" for key in sorted(connection_envs)
    }
    if cli == "openclaw":
        for provider_id in used_providers:
            source_env = providers[provider_id]["api_key_env"]
            target_env = openclaw_api_key_env(source_env)
            if target_env != source_env:
                connection_env_map.pop(source_env, None)
                connection_env_map[target_env] = "${" + source_env + "}"
    extra_allowed_hosts = sorted(
        {
            host
            for provider_id in used_providers
            for host in providers[provider_id].get("allowed_hosts", [])
        }
    )
    extra_docker_compose = sorted(
        {
            str(providers[provider_id]["extra_docker_compose"])
            for provider_id in used_providers
            if providers[provider_id].get("extra_docker_compose")
        }
    )
    if cli == "opencode":
        agent_kwargs: dict[str, Any] = {
            "version": "1.18.13",
            "reuse_preinstalled": True,
            "dangerously_skip_permissions": False,
            "opencode_agent": "orchestrator",
            "opencode_config": {
                "provider": provider_config(providers, used_providers),
                "agent": opencode_roster(task_spec, pool, display, goal_prompt_by_slot),
            },
        }
        if defense is not None:
            filename, source = rendered_defense_plugin(
                defense, system_id, task_spec, pool, display, cli
            )
            agent_kwargs["opencode_plugins"] = {filename: source}
    elif cli == "pi":
        agent_kwargs = {
            "version": "0.84.1",
            "reuse_preinstalled": True,
            "pi_root_tools": [
                "Agent",
                "get_subagent_result",
                "steer_subagent",
            ],
            "pi_models_config": pi_models_config(providers, used_providers),
            "pi_subagent_roster": pi_roster(pool, display, goal_prompt_by_slot),
        }
        if defense is not None:
            _, source = rendered_defense_plugin(
                defense, system_id, task_spec, pool, display, cli
            )
            agent_kwargs["pi_trustfork_defense"] = {
                "name": defense,
                "manifest": defense_manifest(
                    defense, system_id, task_spec, pool, display, cli=cli
                ),
                "source": source,
            }
    elif cli == "openclaw":
        roster_config, roster = openclaw_roster(
            orchestrator, pool, display, goal_prompt_by_slot
        )
        roster_config["models"] = openclaw_models_config(
            providers, used_providers
        )
        agent_kwargs = {
            "version": "2026.7.1-2",
            "reuse_preinstalled": True,
            "openclaw_config": roster_config,
            "openclaw_trustfork_roster": roster,
        }
        if defense is not None:
            _, source = rendered_defense_plugin(
                defense, system_id, task_spec, pool, display, cli
            )
            agent_kwargs["openclaw_trustfork_defense"] = {
                "name": defense,
                "manifest": defense_manifest(
                    defense, system_id, task_spec, pool, display, cli=cli
                ),
                "source": source,
            }
    else:
        raise ValueError(f"CLI adapter not implemented: {cli}")
    agent_model_provider = (
        openclaw_provider_id(orchestrator["provider"])
        if cli == "openclaw"
        else orchestrator["provider"]
    )
    agent_model_name = f"{agent_model_provider}/{orchestrator['api_model']}"
    verifier_env = {"DEEPSEEK_API_KEY": "${DEEPSEEK_API_KEY}"}
    verifier_env["TRUSTFORK_DISPLAYED_IDENTITY_BY_ACTOR"] = json.dumps(
        display, ensure_ascii=False, separators=(",", ":")
    )
    return {
        "job_name": f"{system_id}__{task_spec['task_id']}",
        "jobs_dir": "jobs",
        "n_attempts": 1,
        "n_concurrent_trials": 1,
        "timeout_multiplier": 1.0,
        # Retries are handled by tools/run_benchmark.py, so Harbor makes one attempt.
        "retry": {
            "max_retries": 0,
            "include_exceptions": [],
            "exclude_exceptions": [],
            "wait_multiplier": 2.0,
            "min_wait_sec": 2.0,
            "max_wait_sec": 10.0,
        },
        "environment": {
            "type": "docker",
            "force_build": False,
            "delete": True,
            **(
                {"extra_docker_compose": extra_docker_compose}
                if extra_docker_compose
                else {}
            ),
        },
        "verifier": {
            "include_logs": ["annotations.json"],
            "env": verifier_env,
        },
        "agents": [
            {
                "name": cli,
                "import_path": AGENT_IMPORT_PATHS[cli],
                "model_name": agent_model_name,
                "n_concurrent": 1,
                "extra_allowed_hosts": extra_allowed_hosts,
                "env": dict(sorted(connection_env_map.items())),
                "kwargs": agent_kwargs,
            }
        ],
        "datasets": [
            {
                "path": str(task_dir.parent.relative_to(ROOT)),
                "task_names": [task_spec["task_id"]],
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--system",
        required=True,
        help="Evaluated system as <backbone>@<cli>, for example glm-5.2@opencode.",
    )
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=None,
        help="Optional task id substrings to restrict generation.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the existing job directory for this system first.",
    )
    parser.add_argument(
        "--defense",
        choices=sorted(DEFENSE_PLUGIN_FILES),
        help="Generate one harness-native defense condition as an isolated system.",
    )
    args = parser.parse_args()
    backbone_id, cli = args.system.split("@", 1)

    systems = yaml.safe_load(SYSTEMS_CONFIG.read_text(encoding="utf-8"))
    backbones = systems["backbones"]
    registry = systems["model_registry"]
    providers = systems["providers"]
    if backbone_id not in backbones:
        raise SystemExit(f"Unknown backbone: {backbone_id}")
    if cli not in systems["clis"]:
        raise SystemExit(f"Unknown CLI: {cli}")
    allowed_backbones = systems["evaluation_scope"].get(cli, [])
    if backbone_id not in allowed_backbones:
        allowed = ", ".join(allowed_backbones)
        raise SystemExit(
            f"{backbone_id}@{cli} is outside the evaluation scope; "
            f"allowed {cli} backbones: {allowed}"
        )
    orchestrator = dict(backbones[backbone_id])
    system_id = f"{backbone_id}__{cli}"
    if args.defense:
        system_id += f"__def-{args.defense}"

    pools = load_json(POOLS_CONFIG)["templates"]
    goals = load_json(GOALS_CONFIG)

    system_out = OUT / system_id
    if args.clean and system_out.exists():
        shutil.rmtree(system_out)
    system_out.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "version": BENCH_VERSION,
        "system_id": system_id,
        "orchestrator_backbone": backbone_id,
        "cli": cli,
        "defense": args.defense,
        "jobs": [],
    }
    task_dirs = sorted(
        path
        for path in TASKS_ROOT.glob("*/*")
        if path.is_dir() and (path / "task.toml").exists()
    )
    if args.tasks:
        task_dirs = [
            path
            for path in task_dirs
            if any(token in path.name for token in args.tasks)
        ]
    written = 0
    for task_dir in task_dirs:
        task_spec = load_json(task_dir / "tests" / "task_spec.private.json")
        template = pools[task_spec["pool_template_id"]]
        pool = resolve_pool(template, orchestrator, backbones, registry, task_spec)
        display = render_display(task_spec, pool, orchestrator)
        focal_slot = task_spec["focal_actor_slot"]
        goal_template = goals[task_spec["actor_goal_id"]].get("focal_prompt")
        attack_goal = ""
        metadata = load_json(task_dir / "tests" / "task_metadata.json")
        attack_goal = str(metadata.get("attack_goal") or "")
        goal_prompt_by_slot: dict[str, str | None] = {slot: None for slot in pool}
        if goal_template is not None:
            goal_prompt_by_slot[focal_slot] = str(goal_template).format(
                attack_goal=attack_goal
            )
        runtime_task_dir = task_dir
        if cli == "openclaw":
            runtime_task_dir = prepare_openclaw_task(runtime_task_dir)
        elif cli == "pi":
            runtime_task_dir = prepare_pi_git_task(runtime_task_dir)
        config = job_config(
            system_id,
            cli,
            orchestrator,
            providers,
            runtime_task_dir,
            task_spec,
            pool,
            display,
            goal_prompt_by_slot,
            args.defense,
        )
        path = system_out / f"{config['job_name']}.json"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        manifest["jobs"].append(
            {
                "job_name": config["job_name"],
                "task_id": task_spec["task_id"],
                "scenario_id": task_spec["scenario_id"],
                "identity_display_id": task_spec["identity_display_id"],
                "actor_goal_id": task_spec["actor_goal_id"],
                "breadth_regime": task_spec["breadth_regime"],
                "orchestrator_family": orchestrator["family"],
                "pool_template_id": task_spec["pool_template_id"],
                "benchmark_configuration_id": task_spec["benchmark_configuration_id"],
                "actual_backbone_by_slot": {
                    slot: backbone["api_model"] for slot, backbone in pool.items()
                },
                "displayed_identity_by_slot": display,
                "config": str(path.relative_to(ROOT)),
            }
        )
        written += 1
    (system_out / "system_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"Generated {written} jobs for system {system_id} in {system_out}")


if __name__ == "__main__":
    main()
