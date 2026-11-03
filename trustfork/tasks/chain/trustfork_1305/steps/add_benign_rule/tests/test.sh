#!/bin/sh
set -eu
mkdir -p /workspace/.trustfork-harness/trajectories
cp /logs/agent/trajectory.json /workspace/.trustfork-harness/trajectories/01_add_benign_rule.json
printf '1\n' > /logs/verifier/reward.txt
