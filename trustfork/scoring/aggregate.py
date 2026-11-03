#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
# All eight reported measures are 0--100 and lower-is-better. TH and TUL are
# the inverted terminal-safety and task-utility anchors.
BENCHMARK_METRICS = ("RTF", "RSR", "IAS", "SAF", "VF", "EI", "TH", "TUL")
METRIC_DIRECTION = {metric: "lower_is_better" for metric in BENCHMARK_METRICS}
ANCHOR_NAMES = (
    "RTF", "RSR", "IAS", "SAF", "VF", "EI", "terminal_safety", "task_utility"
)


def find_trial_records() -> list[dict[str, Any]]:
    records = []
    jobs_root = globals().get("JOBS_ROOT", ROOT / "jobs")
    for reward_path in jobs_root.rglob("reward.json"):
        try:
            reward = json.loads(reward_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        annotation_paths = list(reward_path.parent.parent.rglob("annotations.json"))
        annotation = {}
        if annotation_paths:
            try:
                annotation = json.loads(annotation_paths[0].read_text())
            except (OSError, json.JSONDecodeError):
                pass
        records.append(
            {
                "reward_path": str(reward_path),
                "job_dir": next(
                    (part for part in reward_path.parts if "__trustfork_" in part),
                    reward_path.parent.name,
                ),
                "reward": reward,
                "benchmark_scores": annotation.get("benchmark_scores", {}),
                "annotation": annotation,
            }
        )
    return records


def system_id_of(record: dict[str, Any]) -> str:
    job_dir = record["job_dir"]
    marker = "__trustfork_"
    if marker in job_dir:
        return job_dir.split(marker, 1)[0]
    return job_dir


def _mean_skipping_null(
    rows: list[dict[str, Any]], field: str, names: tuple[str, ...]
) -> tuple[dict[str, float], dict[str, int]]:
    means: dict[str, float] = {}
    counts: dict[str, int] = {}
    for name in names:
        values = [
            float(value)
            for row in rows
            for value in [(row["benchmark_scores"].get(field) or {}).get(name)]
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        counts[name] = len(values)
        if values:
            means[name] = statistics.fmean(values)
    return means, counts


def metric_means(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored_rows = [
        row for row in rows if row["benchmark_scores"].get("report_score_0_100")
    ]
    report, counts = _mean_skipping_null(
        scored_rows, "report_score_0_100", BENCHMARK_METRICS
    )
    anchors, _ = _mean_skipping_null(scored_rows, "anchor_score_0_5", ANCHOR_NAMES)
    return {
        "n": len(rows),
        "n_benchmark_scored": len(scored_rows),
        "n_non_null_by_metric": counts,
        "anchor_score_mean_0_5": anchors,
        "report_score_mean_0_100": report,
        "mean": report,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=ROOT / "jobs")
    parser.add_argument("--out", type=Path, default=Path("metrics.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    global JOBS_ROOT
    JOBS_ROOT = args.results if args.results.is_absolute() else ROOT / args.results
    records = find_trial_records()
    by_configuration: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    task_ids_by_system: dict[str, set[str]] = defaultdict(set)
    semantic = Counter()
    for record in records:
        annotation = record["annotation"]
        identity = annotation.get("identity_display_id", annotation.get("condition", "unknown"))
        goal = annotation.get("actor_goal_id", "unknown")
        breadth = annotation.get("breadth_regime", "unknown")
        pool = annotation.get("pool_template_id", "unknown")
        pool_size = annotation.get("available_pool_size", "unknown")
        cell = f"{identity}/{goal}/{breadth}/{pool}"
        by_configuration[cell].append(record)
        system_id = system_id_of(record)
        by_system[system_id].append(record)
        task_id = annotation.get("task_id", "unknown")
        task_ids_by_system[system_id].add(task_id)
        labels = (
            record["annotation"].get("trajectory_pass", {}).get("labels", {})
        )
        observations = record["annotation"].get("code_extracted_observations", {})
        orchestration = record["annotation"].get("orchestration_stats", {})
        first_call = observations.get("subagent_consulted_first", "none")
        called = orchestration.get("k", 0)
        semantic[f"K={pool_size}/first_call={first_call}"] += 1
        semantic[f"K={pool_size}/k={called}"] += 1
        semantic[f"K={pool_size}/N_calls={orchestration.get('N_calls', 0)}"] += 1
        semantic[
            f"K={pool_size}/N_responded={orchestration.get('N_responded', 0)}"
        ] += 1
        for key in (
            "primary_adopted_source",
            "trust_update_class",
            "final_state",
        ):
            semantic[f"K={pool_size}/{key}={labels.get(key, 'unknown')}"] += 1
    configuration_summary = {
        configuration: metric_means(rows)
        for configuration, rows in sorted(by_configuration.items())
    }

    matched: set[str] | None = None
    for system_id, task_ids in task_ids_by_system.items():
        matched = task_ids if matched is None else (matched & task_ids)
    matched = matched or set()
    system_summary: dict[str, Any] = {}
    for system_id, rows in sorted(by_system.items()):
        matched_rows = [
            row
            for row in rows
            if row["annotation"].get("task_id") in matched
        ]
        by_factor: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in matched_rows:
            annotation = row["annotation"]
            key = (
                f"{annotation.get('identity_display_id', annotation.get('condition', 'unknown'))}/"
                f"{annotation.get('actor_goal_id', 'unknown')}/"
                f"{annotation.get('breadth_regime', 'unknown')}/"
                f"{annotation.get('pool_template_id', 'unknown')}"
            )
            by_factor[key].append(row)
        system_summary[system_id] = {
            "matched_task_count": len(
                {
                    row["annotation"].get("task_id")
                    for row in matched_rows
                }
            ),
            **metric_means(matched_rows),
            "by_task_factors": {
                key: metric_means(factor_rows)
                for key, factor_rows in sorted(by_factor.items())
            },
        }
    summary = {
        "n_run_records": len(records),
        "matched_task_count_across_systems": len(matched),
        "metric_direction": METRIC_DIRECTION,
        "by_task_factors": configuration_summary,
        "by_system_on_matched_tasks": system_summary,
        "semantic_counts": dict(sorted(semantic.items())),
    }
    out = args.out if args.out.is_absolute() else ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
