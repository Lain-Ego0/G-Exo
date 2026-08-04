#!/usr/bin/env bash
# Start the model currently deployed on the K3 (OpenAI-compatible API).
# Usage: MODEL_PATH=/path/to/model.gguf ./start_llama_server.sh
set -euo pipefail

LLAMA_SERVER="${LLAMA_SERVER:-/usr/bin/llama-server}"
MODEL_PATH="${MODEL_PATH:-$HOME/.cache/models/llm/Qwen3.5-0.8B-Q4_0.gguf}"
PORT="${LLAMA_PORT:-9193}"
CTX="${LLAMA_CTX:-4096}"
THREADS="${LLAMA_THREADS:-8}"

if [[ ! -f "$MODEL_PATH" ]]; then
    echo "model not found: $MODEL_PATH" >&2
    echo "set MODEL_PATH to the GGUF already installed on this device" >&2
    exit 1
fi

if [[ ! -x "$LLAMA_SERVER" ]]; then
    echo "llama-server not executable: $LLAMA_SERVER" >&2
    exit 1
fi

exec "$LLAMA_SERVER" \
    -m "$MODEL_PATH" \
    --host 127.0.0.1 \
    --port "$PORT" \
    -c "$CTX" \
    -t "$THREADS" \
    --no-webui
