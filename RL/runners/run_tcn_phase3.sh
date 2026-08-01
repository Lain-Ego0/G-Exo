#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="$(dirname "$PROJECT_ROOT")"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

: "${GEXO_DATA_ROOT:?Set GEXO_DATA_ROOT before running this script}"

DEVICE="${TCN_DEVICE:-auto}"
PHASE3_RAW_ROOT="$GEXO_DATA_ROOT/Parsed"
PHASE3_CACHE="${GEXO_PHASE3_CACHE:-$GEXO_DATA_ROOT/processed/tcn50_phase3}"
MANIFEST="$PROJECT_ROOT/RL/assets/datasets/phase3_test_manifest.json"
OUTPUT_ROOT="$PROJECT_ROOT/RL/outputs/tcn_phase3"
RUNS_ROOT="$PROJECT_ROOT/RL/outputs/tcn_runs"

cd "$WORKSPACE_ROOT"

python -m RL.data.dataset_manifest \
    --dataset-root "$PHASE3_RAW_ROOT" \
    --output "$MANIFEST" \
    --include-subjects BT18 BT19 BT20 BT21 BT22 BT23 BT24 \
    --fixed-split test

python -m RL.data.preprocess_tcn \
    --manifest "$MANIFEST" \
    --output-root "$PHASE3_CACHE" \
    --remove-stale \
    --overwrite

for seed in 42 43 44; do
    run="$RUNS_ROOT/seed_${seed}"

    python -m RL.runners.evaluate_tcn \
        --device "$DEVICE" \
        --split test \
        --data-root "$PHASE3_CACHE" \
        --checkpoint "$run/best_model.pt" \
        --output "$run/phase3_evaluation.json"
done

python -m RL.runners.aggregate_tcn_runs \
    --evaluation-name phase3_evaluation.json \
    --output "$OUTPUT_ROOT/aggregate.json"

python -m RL.runners.report_tcn_phase3 \
    --processed-root "$PHASE3_CACHE"
