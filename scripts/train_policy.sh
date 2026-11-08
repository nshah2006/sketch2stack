#!/usr/bin/env bash
# Train a policy on the twin dataset with LeRobot (separate venv).
#   scripts/train_policy.sh act   [steps]   # small, fast: the first check that learning works
#   scripts/train_policy.sh groot [steps]   # GR00T fine-tune (big GPU)
#   scripts/train_policy.sh smolvla [steps]
# GPU: set CUDA_VISIBLE_DEVICES (default 1, so the fleet keeps GPU 0 busier).
set -euo pipefail
POLICY=${1:-act}
STEPS=${2:-20000}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LR=${LEROBOT_VENV:-/mnt/Data/Tushaar/lerobot_venv}
DATA=${DATA:-$ROOT/sidekick_data/lerobot/sidekick_twin}
OUT=$ROOT/sidekick_data/policies/${POLICY}_$(date +%m%d_%H%M)
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-1}
case $POLICY in
  act)     BS=32 ;;
  smolvla) BS=32 ;;
  groot)   BS=16 ;;
  *)       BS=16 ;;
esac
echo "training $POLICY on $DATA -> $OUT (gpu $CUDA_VISIBLE_DEVICES, $STEPS steps, batch $BS)"
exec "$LR/bin/lerobot-train" \
  --dataset.repo_id=local/sidekick_twin --dataset.root="$DATA" \
  --policy.type="$POLICY" --policy.device=cuda --policy.push_to_hub=false \
  --output_dir="$OUT" --job_name="sidekick_$POLICY" \
  --steps="$STEPS" --batch_size="$BS" --num_workers=8 \
  --save_freq=${SAVE_FREQ:-5000} --log_freq=100 --trackio.enable=false
