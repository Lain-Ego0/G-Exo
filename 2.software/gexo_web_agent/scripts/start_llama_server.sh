#!/usr/bin/env bash
# Start llama-server with the Qwen3-4B model (OpenAI-compatible API).
# Usage: MODEL_PATH=/path/to/model.gguf ./start_llama_server.sh
set -euo pipefail

MODEL_PATH="${MODEL_PATH:-$HOME/models/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf}"
PORT="${LLAMA_PORT:-8080}"
CTX="${LLAMA_CTX:-8192}"
THREADS="${LLAMA_THREADS:-$(nproc)}"

if [[ ! -f "$MODEL_PATH" ]]; then
    echo "model not found: $MODEL_PATH" >&2
    echo "set MODEL_PATH=/path/to/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf" >&2
    exit 1
fi

exec llama-server \
    --model "$MODEL_PATH" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --ctx-size "$CTX" \
    --threads "$THREADS" \
    --jinja
