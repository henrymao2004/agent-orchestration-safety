#!/usr/bin/env python3

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
CONFIG_PATH = PACKAGE / "config" / "formal_eval_matrix.yaml"
SYSTEMS_PATH = PACKAGE / "config" / "systems.yaml"
TASKS_ROOT = PACKAGE / "tasks"


def main() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    systems = yaml.safe_load(SYSTEMS_PATH.read_text(encoding="utf-8"))
    specs: list[dict[str, Any]] = []
    for task_dir in sorted(
        path for path in TASKS_ROOT.glob("*/*") if path.is_dir()
    ):
        spec_path = task_dir / "tests" / "task_spec.private.json"
        if spec_path.exists():
            specs.append(json.loads(spec_path.read_text(encoding="utf-8")))
    if not specs:
        raise SystemExit("No materialized tasks found; run materialize_tasks.py")

    scenario_ids = {spec["scenario_id"] for spec in specs}
    configuration_ids = {spec["benchmark_configuration_id"] for spec in specs}
    backbones = systems["backbones"]
    clis = systems["clis"]
    active_clis = [cli for cli, row in clis.items() if row["status"] == "active"]
    evaluation_scope = systems["evaluation_scope"]
    evaluated_systems = [
        (backbone, cli)
        for cli in active_clis
        for backbone in evaluation_scope[cli]
    ]
    system_count = len(evaluated_systems)
    tasks_per_system = len(specs)

    summary = {
        "version": config["version"],
        "task_definition": (
            "scenario x identity x goal x breadth x pool_template"
        ),
        "scenario_count": len(scenario_ids),
        "benchmark_configuration_count": len(configuration_ids),
        "materialized_task_count": len(specs),
        "tasks_per_system": tasks_per_system,
        "backbone_count": len(backbones),
        "active_cli_count": len(active_clis),
        "system_count": system_count,
        "evaluated_systems": [
            f"{backbone}@{cli}" for backbone, cli in evaluated_systems
        ],
        "planned_run_count_all_systems": tasks_per_system * system_count,
        "tasks_by_identity": dict(
            sorted(Counter(spec["identity_display_id"] for spec in specs).items())
        ),
        "tasks_by_goal": dict(
            sorted(Counter(spec["actor_goal_id"] for spec in specs).items())
        ),
        "tasks_by_breadth": dict(
            sorted(Counter(spec["breadth_regime"] for spec in specs).items())
        ),
        "tasks_by_pool_template": dict(
            sorted(Counter(spec["pool_template_id"] for spec in specs).items())
        ),
    }
    out = PACKAGE / "dataset_matrix.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
