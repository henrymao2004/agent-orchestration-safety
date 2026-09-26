#!/usr/bin/env python3
"""Run one evaluated system's per-task Harbor jobs with a bounded retry policy.

A task gets at most MAX_ATTEMPTS attempts and is repeated only when an attempt
leaves no valid reward artifact or records no subagent call. The first valid
record is retained and scores never select an attempt. Superseded attempts move
to build/attempts/<job>/ so that jobs/ holds one record per task.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
LEDGER_PATH = ROOT / "build" / "run_ledger.json"
ATTEMPTS_ROOT = ROOT / "build" / "attempts"
HARBOR_BIN = os.environ.get("HARBOR_BIN", "harbor")
ENSURE_BASE_IMAGE = PACKAGE / "tools" / "ensure_base_image.py"
SYSTEMS_CONFIG = PACKAGE / "config" / "systems.yaml"
POOLS_CONFIG = PACKAGE / "config" / "pool_templates.json"
JUDGE_API_KEY_ENV = "DEEPSEEK_API_KEY"
MAX_ATTEMPTS = 3
DEFENSE_VARIANTS = {
    "def-anonymize-responses",
    "def-check-identity",
    "def-verify-before-action",
}

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_env_file(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def load_ledger(ledger_path: Path) -> dict:
    if ledger_path.exists():
        return json.loads(ledger_path.read_text())
    return {"jobs": {}}


def save_ledger(ledger: dict, ledger_path: Path) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=2) + "\n")
    tmp.replace(ledger_path)


def parse_system_id(system_id: str) -> tuple[str, str, str | None]:
    parts = system_id.split("__")
    if len(parts) not in {2, 3}:
        raise ValueError("--system must use <backbone>__<cli>[__def-<defense>]")
    backbone_id, cli = parts[:2]
    variant = parts[2] if len(parts) == 3 else None
    if variant is not None and variant not in DEFENSE_VARIANTS:
        raise ValueError(f"Unsupported system variant: {variant}")
    return backbone_id, cli, variant


def required_api_keys(systems: dict[str, Any], backbone_id: str) -> set[str]:
    """API keys for every provider the system's pools use, plus the judge.

    Slot rotation only permutes slots, so the provider set does not depend on the task.
    """
    from trustfork.tools.generate_jobs import resolve_pool

    backbones = systems["backbones"]
    orchestrator = backbones[backbone_id]
    templates = json.loads(POOLS_CONFIG.read_text(encoding="utf-8"))["templates"]
    provider_ids = {orchestrator["provider"]}
    for template in templates.values():
        pool = resolve_pool(
            template, orchestrator, backbones, systems["model_registry"]
        )
        provider_ids.update(backbone["provider"] for backbone in pool.values())
    keys = {systems["providers"][pid]["api_key_env"] for pid in provider_ids}
    keys.add(JUDGE_API_KEY_ENV)
    return keys


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def assess_record(job_dir: Path) -> dict[str, Any]:
    """Classify one attempt from its on-disk artifacts, never from its scores.

    A valid record has a non-empty reward.json, the verifier's annotations.json,
    and at least one distinct subagent called.
    """
    reward_path = None
    if job_dir.exists():
        for path in sorted(job_dir.rglob("reward.json")):
            value = read_json(path)
            if isinstance(value, dict) and value:
                reward_path = path
                break
    if reward_path is None:
        return {
            "reward_artifact": False,
            "subagent_calls": None,
            "valid": False,
            "reason": "no reward artifact",
        }
    annotations = None
    for path in sorted(reward_path.parent.parent.rglob("annotations.json")):
        annotations = read_json(path)
        break
    if not isinstance(annotations, dict):
        return {
            "reward_artifact": False,
            "subagent_calls": None,
            "valid": False,
            "reason": "reward artifact without verifier annotations",
        }
    breadth = annotations.get("breadth_validation") or {}
    calls = breadth.get("observed_breadth")
    if calls is None:
        calls = (annotations.get("orchestration_stats") or {}).get("k")
    calls = int(calls) if isinstance(calls, (int, float)) else 0
    return {
        "reward_artifact": True,
        "subagent_calls": calls,
        "valid": calls >= 1,
        "reason": "valid" if calls >= 1 else "no valid subagent call",
    }


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def move_record(source: Path, destination: Path) -> Path:
    if destination.exists():
        destination = destination.with_name(
            f"{destination.name}-{int(time.time())}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return destination


def harbor_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT), os.environ.get("PYTHONPATH", "")]
        ).strip(os.pathsep),
    }


class TaskRunner:
    def __init__(self, ledger: dict, ledger_path: Path) -> None:
        self.ledger = ledger
        self.ledger_path = ledger_path
        self.lock = threading.Lock()

    def persist(self, name: str, entry: dict[str, Any]) -> None:
        with self.lock:
            self.ledger["jobs"][name] = entry
            save_ledger(self.ledger, self.ledger_path)

    def finish_attempt(
        self, attempt: dict[str, Any], job_dir: Path, returncode: int | None
    ) -> None:
        attempt.update(assess_record(job_dir))
        attempt["returncode"] = returncode
        attempt["finished_at"] = time.time()
        attempt["record_path"] = relative(job_dir)

    def archive(self, name: str, attempt: dict[str, Any], job_dir: Path) -> None:
        if job_dir.exists():
            destination = move_record(
                job_dir, ATTEMPTS_ROOT / name / f"attempt-{attempt['attempt']}"
            )
            attempt["record_path"] = relative(destination)
        else:
            attempt["record_path"] = None

    def retain_first_reward_record(
        self, name: str, entry: dict[str, Any], job_dir: Path
    ) -> None:
        """No attempt was valid: keep the first attempt that left a reward
        artifact (manifest order, not score) as the task's record."""
        attempts = entry["attempts"]
        retained = next((a for a in attempts if a.get("reward_artifact")), None)
        entry["retained_attempt"] = retained["attempt"] if retained else None
        if retained is None or retained.get("record_path") == relative(job_dir):
            return
        self.archive(name, attempts[-1], job_dir)
        source = ROOT / str(retained["record_path"])
        if source.exists():
            shutil.move(str(source), str(job_dir))
            retained["record_path"] = relative(job_dir)

    def run(self, path: Path, name: str, rerun: bool) -> tuple[str, dict[str, Any]]:
        config = json.loads(path.read_text())
        job_dir = ROOT / str(config.get("jobs_dir", "jobs")) / name
        with self.lock:
            entry = dict(self.ledger["jobs"].get(name) or {})
        attempts: list[dict[str, Any]] = list(entry.get("attempts") or [])
        if rerun and (attempts or job_dir.exists()):
            if job_dir.exists():
                move_record(
                    job_dir,
                    ATTEMPTS_ROOT / name / f"superseded-{int(time.time())}",
                )
            entry = {"superseded_attempts": attempts}
            attempts = []
        entry["attempts"] = attempts
        entry["max_attempts"] = MAX_ATTEMPTS
        # A record left by an interrupted run already consumed one attempt.
        if attempts and attempts[-1].get("finished_at") is None:
            self.finish_attempt(attempts[-1], job_dir, None)
        elif not attempts and job_dir.exists():
            attempts.append({"attempt": 1, "started_at": None, "adopted": True})
            self.finish_attempt(attempts[-1], job_dir, None)
        while True:
            last = attempts[-1] if attempts else None
            if last is not None and last["valid"]:
                entry["status"] = "valid"
                entry["retained_attempt"] = last["attempt"]
                break
            if len(attempts) >= MAX_ATTEMPTS:
                entry["status"] = "exhausted"
                self.retain_first_reward_record(name, entry, job_dir)
                break
            if last is not None:
                print(
                    f"Retrying {name}: attempt {last['attempt']} had "
                    f"{last['reason']}",
                    flush=True,
                )
                self.archive(name, last, job_dir)
            attempt = {
                "attempt": len(attempts) + 1,
                "started_at": time.time(),
                "finished_at": None,
            }
            attempts.append(attempt)
            entry["status"] = "running"
            self.persist(name, entry)
            print(
                f"Starting {name} (attempt {attempt['attempt']}/{MAX_ATTEMPTS})",
                flush=True,
            )
            completed = subprocess.run(
                [HARBOR_BIN, "jobs", "start", "--config", str(path), "--yes"],
                cwd=ROOT,
                env=harbor_env(),
                check=False,
            )
            self.finish_attempt(attempt, job_dir, completed.returncode)
            self.persist(name, entry)
        entry["finished_at"] = time.time()
        self.persist(name, entry)
        return name, entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--system",
        required=True,
        help="Evaluated system directory under build/jobs (for example "
        "glm-5.2__opencode).",
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--max-jobs", type=int)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Start the selected tasks over as a new run: existing records "
        "move to build/attempts/<job>/superseded-*/ and the attempt budget "
        "resets. Not a retry mechanism.",
    )
    args = parser.parse_args()
    ledger_path = args.ledger if args.ledger.is_absolute() else ROOT / args.ledger
    try:
        backbone_id, cli, variant = parse_system_id(args.system)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    systems = yaml.safe_load(SYSTEMS_CONFIG.read_text(encoding="utf-8"))
    allowed_backbones = systems["evaluation_scope"].get(cli, [])
    if backbone_id not in allowed_backbones:
        allowed = ", ".join(allowed_backbones)
        raise SystemExit(
            f"{backbone_id}@{cli} is outside the evaluation scope; "
            f"allowed {cli} backbones: {allowed}"
        )
    if args.env_file:
        load_env_file(args.env_file)
    required = required_api_keys(systems, backbone_id)
    missing = sorted(key for key in required if not os.environ.get(key))
    if missing:
        raise SystemExit(
            "Missing required environment variables: " + ", ".join(missing)
        )
    subprocess.run([str(ENSURE_BASE_IMAGE)], cwd=ROOT, check=True)

    configs = sorted(
        path
        for path in (ROOT / "build" / "jobs" / args.system).glob("*.json")
        if path.name != "system_manifest.json"
    )
    if args.only:
        configs = [
            path for path in configs if any(token in path.stem for token in args.only)
        ]
    if args.max_jobs is not None:
        configs = configs[: args.max_jobs]
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    ledger = load_ledger(ledger_path)
    pending: list[tuple[Path, str]] = []
    for path in configs:
        name = json.loads(path.read_text())["job_name"]
        status = ledger["jobs"].get(name, {}).get("status")
        if not args.rerun and status in {"valid", "exhausted"}:
            print(f"Skipping finished job {name} ({status})")
            continue
        pending.append((path, name))

    runner = TaskRunner(ledger, ledger_path)
    unscored = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(runner.run, path, name, args.rerun): name
            for path, name in pending
        }
        for future in as_completed(futures):
            name, entry = future.result()
            retained = entry.get("retained_attempt")
            print(
                f"Finished {name}: {entry['status']} after "
                f"{len(entry['attempts'])} attempt(s); retained attempt "
                f"{retained if retained is not None else 'none'}",
                flush=True,
            )
            unscored += int(retained is None)
    if unscored:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
