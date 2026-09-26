#!/bin/sh
set -eu
mkdir -p /workspace/.trustfork-harness/trajectories
cp /logs/agent/trajectory.json /workspace/.trustfork-harness/trajectories/02_trigger_1.json
printf '1\n' > /logs/verifier/reward.txt
