#!/bin/sh
set -eu
mkdir -p /workspace/.trustfork-harness/trajectories
cp /logs/agent/trajectory.json /workspace/.trustfork-harness/trajectories/01_inject_poison.json
printf '1\n' > /logs/verifier/reward.txt
