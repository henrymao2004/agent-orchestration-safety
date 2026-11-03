#!/usr/bin/env python3

from __future__ import annotations

import fcntl
import subprocess
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parent
IMAGE = "trustfork-agents:tf-three-harnesses-v1"
LEGACY_IMAGE = "trustfork-agents:opencode-1.18.13_pi-0.84.1_pi-subagents-0.15.0"
LOCK = ROOT / "build" / "base-image.lock"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def main() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if run(["docker", "image", "inspect", IMAGE]).returncode == 0:
            print(f"Reusing shared base image {IMAGE}")
            return
        command = [
                "docker",
                "build",
        ]
        if run(["docker", "image", "inspect", LEGACY_IMAGE]).returncode == 0:
            command.extend(
                [
                    "--file",
                    str(PACKAGE / "base-image" / "Dockerfile.openclaw-layer"),
                    "--build-arg",
                    f"BASE_IMAGE={LEGACY_IMAGE}",
                ]
            )
        command.extend(
            [
                "--build-arg",
                "OPENCODE_VERSION=1.18.13",
                "--build-arg",
                "PI_VERSION=0.84.1",
                "--build-arg",
                "PI_SUBAGENTS_VERSION=0.15.0",
                "--build-arg",
                "PI_SOURCE_COMMIT=534bcbffb7e1e7551d9ee3572dfeb278e203e493",
                "--build-arg",
                "OPENCLAW_VERSION=2026.7.1-2",
                "--build-arg",
                "NODE_VERSION=24.15.0",
                "--tag",
                IMAGE,
                str(PACKAGE / "base-image"),
            ]
        )
        completed = run(command)
        if completed.returncode:
            tail = "\n".join(completed.stdout.splitlines()[-60:])
            raise SystemExit(f"Shared base image build failed:\n{tail}")
        print(f"Built shared base image {IMAGE}")


if __name__ == "__main__":
    main()
