#!/usr/bin/env bash
# Start the twin fleet in the background. Extra args go to sidekick.fleet.
#   scripts/run_fleet.sh -n 10 --speed 2 --record
# Watch: http://127.0.0.1:8765   Stop: scripts/stop_fleet.sh
cd "$(dirname "$0")/.."
OUT=${OUT:-sidekick_data/fleet}
mkdir -p "$OUT"
export SIDEKICK_GL=${SIDEKICK_GL:-/mnt/Data/Tushaar/nvidia_userspace} OMP_NUM_THREADS=2
nohup venv/bin/python -m sidekick.fleet --out "$OUT" "$@" > "$OUT/fleet.log" 2>&1 &
echo "fleet pid $!  log $OUT/fleet.log"
