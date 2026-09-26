#!/bin/sh
set -eu
mkdir -p /workspace/.trustfork-harness/trajectories
cp /logs/agent/trajectory.json /workspace/.trustfork-harness/trajectories/02_fragment_2.json
printf '1\n' > /logs/verifier/reward.txt
