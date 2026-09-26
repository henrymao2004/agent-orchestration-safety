#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
JOBS_ROOT = ROOT / "jobs"
METRIC_POLICY_PATH = PACKAGE / "config" / "defense_metric_policy.json"
REQUIRED_PLUGIN_EVENTS = {
    "anonymize-responses": {"plugin_initialized", "roster_anonymized"},
    "check-identity": {"plugin_initialized", "roster_identity_attested"},
    "verify-before-action": {"plugin_initialized"},
}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def load_metric_policy() -> dict[str, bool]:
    policy = {"require_tokens": True}
    if not METRIC_POLICY_PATH.is_file():
        return policy
    configured = read_json(METRIC_POLICY_PATH).get("required_metrics") or {}
    if isinstance(configured.get("tokens_per_task"), bool):
        policy["require_tokens"] = configured["tokens_per_task"]
    return policy


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def trajectory_tokens(
    trajectory: dict[str, Any], *, final_metrics_include_subagents: bool = False
) -> int:
    metrics = trajectory.get("final_metrics") or {}
    total = int(metrics.get("total_prompt_tokens") or 0) + int(
        metrics.get("total_completion_tokens") or 0
    )
    if final_metrics_include_subagents:
        return total
    for child in trajectory.get("subagent_trajectories") or []:
        if isinstance(child, dict):
            total += trajectory_tokens(child)
    return total


def load_plugin_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid defense JSONL at {path}:{line_number}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"Non-object defense event at {path}:{line_number}")
        events.append(event)
    return events


def trial_directory(job_dir: Path) -> Path | None:
    candidates = [
        path.parent for path in job_dir.glob("*/result.json") if path.parent != job_dir
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def fragment_directories(
    trial_dir: Path, trial_result: dict[str, Any] | None = None
) -> list[Path]:
    steps_root = trial_dir / "steps"
    fragments = (
        [path for path in steps_root.iterdir() if path.is_dir()]
        if steps_root.is_dir()
        else []
    )
    if not fragments:
        return [trial_dir]

    by_name = {path.name: path for path in fragments}
    ordered: list[Path] = []
    for step in (trial_result or {}).get("step_results") or []:
        if not isinstance(step, dict):
            continue
        step_name = step.get("step_name")
        if isinstance(step_name, str) and step_name in by_name:
            ordered.append(by_name.pop(step_name))

    def natural_name(path: Path) -> tuple[tuple[int, int | str], ...]:
        parts: list[tuple[int, int | str]] = []
        text = path.name
        cursor = 0
        for index, character in enumerate(text):
            if character.isdigit() == text[cursor].isdigit():
                continue
            part = text[cursor:index]
            parts.append((0, int(part)) if part.isdigit() else (1, part))
            cursor = index
        part = text[cursor:]
        parts.append((0, int(part)) if part.isdigit() else (1, part))
        return tuple(parts)

    return ordered + sorted(by_name.values(), key=natural_name)


def final_artifact(fragments: list[Path], relative: Path) -> Path | None:
    candidates = [fragment / relative for fragment in fragments]
    existing = [path for path in candidates if path.is_file()]
    return existing[-1] if existing else None


def execution_window(
    trial_result: dict[str, Any],
) -> tuple[datetime | None, datetime | None]:
    execution = trial_result.get("agent_execution") or {}
    started = parse_timestamp(execution.get("started_at"))
    finished = parse_timestamp(execution.get("finished_at"))
    if started is not None and finished is not None:
        return started, finished

    step_windows: list[tuple[datetime, datetime]] = []
    for step in trial_result.get("step_results") or []:
        if not isinstance(step, dict):
            continue
        step_execution = step.get("agent_execution") or {}
        step_started = parse_timestamp(step_execution.get("started_at"))
        step_finished = parse_timestamp(step_execution.get("finished_at"))
        if step_started is not None and step_finished is not None:
            step_windows.append((step_started, step_finished))
    if step_windows:
        return min(start for start, _ in step_windows), max(
            finish for _, finish in step_windows
        )
    return (
        parse_timestamp(trial_result.get("started_at")),
        parse_timestamp(trial_result.get("finished_at")),
    )


def task_id_from_job(system_id: str, job_dir: Path) -> str:
    prefix = system_id + "__"
    return job_dir.name.removeprefix(prefix)


def collect_system(
    system_id: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    records: dict[str, dict[str, Any]] = {}
    invalid: list[dict[str, Any]] = []
    defense = system_id.partition("__def-")[2] or None
    parts = system_id.split("__")
    if len(parts) < 2 or parts[1] not in {"opencode", "pi", "openclaw"}:
        raise ValueError(f"Unsupported TrustFork system id: {system_id}")
    harness = parts[1]
    metric_policy = load_metric_policy()
    job_dirs = sorted(
        path for path in JOBS_ROOT.glob(f"{system_id}__*") if path.is_dir()
    )
    for job_dir in job_dirs:
        task_id = task_id_from_job(system_id, job_dir)
        if not task_id.startswith("trustfork_"):
            continue
        reasons: list[str] = []
        job_result_path = job_dir / "result.json"
        if not job_result_path.is_file():
            invalid.append({"task_id": task_id, "reasons": ["missing_job_result"]})
            continue
        job_result = read_json(job_result_path)
        stats = job_result.get("stats") or {}
        if stats.get("n_completed_trials") != 1 or stats.get("n_errored_trials"):
            reasons.append("job_not_clean_complete")

        trial_dir = trial_directory(job_dir)
        if trial_dir is None:
            invalid.append({"task_id": task_id, "reasons": reasons + ["missing_trial"]})
            continue
        trial_result_path = trial_dir / "result.json"
        trial_result = (
            read_json(trial_result_path) if trial_result_path.is_file() else None
        )
        fragments = fragment_directories(trial_dir, trial_result)
        trajectory_path = final_artifact(fragments, Path("agent/trajectory.json"))
        annotations_path = final_artifact(
            fragments, Path("verifier/annotations.json")
        )
        if not trial_result_path.is_file():
            reasons.append("missing_trial_result")
        if trajectory_path is None:
            reasons.append("missing_trajectory")
        if annotations_path is None:
            reasons.append("missing_annotations")
        if reasons:
            invalid.append({"task_id": task_id, "reasons": reasons})
            continue

        assert trial_result is not None
        trajectory = read_json(trajectory_path)
        annotations = read_json(annotations_path)
        tokens = trajectory_tokens(
            trajectory,
            final_metrics_include_subagents=harness in {"pi", "openclaw"},
        )
        if tokens <= 0 and metric_policy["require_tokens"]:
            reasons.append("zero_total_trajectory_tokens")
        started, finished = execution_window(trial_result)
        if started is None or finished is None or finished < started:
            reasons.append("invalid_wall_clock")

        plugin_events: list[dict[str, Any]] = []
        if defense is not None:
            plugin_paths = [
                fragment / "agent" / harness / "defense" / "events.jsonl"
                for fragment in fragments
            ]
            plugin_events = [
                event
                for plugin_path in plugin_paths
                for event in load_plugin_events(plugin_path)
            ]
            observed = {str(event.get("event")) for event in plugin_events}
            missing = REQUIRED_PLUGIN_EVENTS.get(defense, set()) - observed
            if missing:
                reasons.append("missing_plugin_events:" + ",".join(sorted(missing)))
            if any(event.get("task_id") != task_id for event in plugin_events):
                reasons.append("plugin_task_id_mismatch")

        if reasons:
            invalid.append({"task_id": task_id, "reasons": reasons})
            continue
        labels = (annotations.get("trajectory_pass") or {}).get("labels") or {}
        records[task_id] = {
            "task_id": task_id,
            "tokens": tokens if tokens > 0 else None,
            "wall_clock_seconds": (finished - started).total_seconds(),
            "subagent_calls": int(
                ((annotations.get("orchestration_stats") or {}).get("N_calls")) or 0
            ),
            "verification_passed": labels.get("verification_before_action"),
            "plugin_event_counts": dict(
                Counter(str(event.get("event")) for event in plugin_events)
            ),
        }
    return records, invalid


def mean(values: list[float | int]) -> float | None:
    return statistics.fmean(values) if values else None


def summarize(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    verification = [
        bool(record["verification_passed"])
        for record in records.values()
        if record["verification_passed"] is not None
    ]
    token_values = [
        record["tokens"]
        for record in records.values()
        if record["tokens"] is not None
    ]
    return {
        "n_valid": len(records),
        "mean_tokens": mean(token_values),
        "n_token_evaluable": len(token_values),
        "mean_wall_clock_seconds": mean(
            [record["wall_clock_seconds"] for record in records.values()]
        ),
        "mean_subagent_calls": mean(
            [record["subagent_calls"] for record in records.values()]
        ),
        "verification_pass_rate": mean([int(value) for value in verification]),
        "n_verification_evaluable": len(verification),
    }


def paired_overhead(
    baseline: dict[str, dict[str, Any]],
    defense: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    tasks = sorted(set(baseline) & set(defense))
    token_tasks = [
        task
        for task in tasks
        if baseline[task]["tokens"] is not None
        and defense[task]["tokens"] is not None
    ]
    token_delta = [
        defense[task]["tokens"] - baseline[task]["tokens"]
        for task in token_tasks
    ]
    latency_delta = [
        defense[task]["wall_clock_seconds"] - baseline[task]["wall_clock_seconds"]
        for task in tasks
    ]
    call_delta = [
        defense[task]["subagent_calls"] - baseline[task]["subagent_calls"]
        for task in tasks
    ]
    paired_verification = [
        (
            bool(baseline[task]["verification_passed"]),
            bool(defense[task]["verification_passed"]),
        )
        for task in tasks
        if baseline[task]["verification_passed"] is not None
        and defense[task]["verification_passed"] is not None
    ]
    return {
        "n_paired": len(tasks),
        "n_token_paired": len(token_tasks),
        "mean_token_increment": mean(token_delta),
        "mean_wall_clock_increment_seconds": mean(latency_delta),
        "mean_subagent_call_increment": mean(call_delta),
        "verification_pass_rate_baseline": mean(
            [int(before) for before, _ in paired_verification]
        ),
        "verification_pass_rate_defense": mean(
            [int(after) for _, after in paired_verification]
        ),
        "verification_pass_rate_increment": mean(
            [int(after) - int(before) for before, after in paired_verification]
        ),
        "n_verification_paired": len(paired_verification),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--system", required=True)
    parser.add_argument(
        "--baseline",
        help="Default system id for paired overhead, e.g. gpt-5.6-luna__opencode.",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any discovered trial is invalid.",
    )
    args = parser.parse_args()

    records, invalid = collect_system(args.system)
    report: dict[str, Any] = {
        "schema_version": "trustfork-defense-audit-v1",
        "system_id": args.system,
        "metric_policy": load_metric_policy(),
        "summary": summarize(records),
        "n_invalid": len(invalid),
        "invalid": invalid,
    }
    if args.baseline:
        baseline_records, baseline_invalid = collect_system(args.baseline)
        report["baseline_system_id"] = args.baseline
        report["baseline_summary"] = summarize(baseline_records)
        report["baseline_n_invalid"] = len(baseline_invalid)
        report["paired_overhead"] = paired_overhead(baseline_records, records)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.strict and invalid:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
