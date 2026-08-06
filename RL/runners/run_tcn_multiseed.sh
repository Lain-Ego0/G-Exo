#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(dirname "$PROJECT_ROOT")"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

: "${GEXO_DATA_ROOT:?Set GEXO_DATA_ROOT before running this script}"

python - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("CUDA is not available in this environment.")
print("CUDA:", torch.cuda.get_device_name(0))
PY

seeds=("$@")
if [[ ${#seeds[@]} -eq 0 ]]; then
    seeds=(42 43 44)
fi

cd "$WORKSPACE_ROOT"

for seed in "${seeds[@]}"; do
    output="$PROJECT_ROOT/RL/outputs/tcn_runs/seed_${seed}"

    python -m RL.runners.pretrain_tcn \
        --device cuda \
        --seed "$seed" \
        --epochs 30 \
        --batch-size 256 \
        --num-workers 4 \
        --output "$output"

    python -m RL.runners.check_tcn_pipeline \
        --checkpoint "$output/best_model.pt" \
        --output "$output/pipeline_check.json"

    python -m RL.runners.evaluate_tcn \
        --device cuda \
        --checkpoint "$output/best_model.pt"
done

python -m RL.runners.aggregate_tcn_runs
