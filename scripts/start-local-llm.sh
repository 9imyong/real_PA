#!/usr/bin/env bash
# Development GPU server. Conversation history remains owned by real-PA.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
model=${1:-"$repo_root/../stt_test/models/llm/Qwen3.5-0.8B-Q4_0.gguf"}
if (( $# > 1 )) || [[ ! -f "$model" ]]; then
  echo 'Usage: bash scripts/start-local-llm.sh [existing-model.gguf]' >&2
  exit 2
fi
model=$(realpath -- "$model")
cache_mib=${REAL_PA_LLM_CACHE_MIB:-256}
context_tokens=${REAL_PA_LLM_CONTEXT:-8192}
if [[ ! "$cache_mib" =~ ^[0-9]+$ ]]; then
  echo 'REAL_PA_LLM_CACHE_MIB must be a nonnegative integer.' >&2
  exit 2
fi
if [[ ! "$context_tokens" =~ ^[0-9]+$ ]] || (( 10#$context_tokens < 512 || 10#$context_tokens > 32768 )); then
  echo 'REAL_PA_LLM_CONTEXT must be an integer between 512 and 32768.' >&2
  exit 2
fi
docker run --pull never --rm -d --name real-pa-llm-dev --gpus all \
  -p 127.0.0.1:18181:8080 \
  --mount "type=bind,source=$(dirname -- "$model"),target=/models,readonly" \
  localforge/llama-cuda:56b9eb280a67 \
  --model "/models/$(basename -- "$model")" --host 0.0.0.0 --port 8080 \
  --ctx-size "$context_tokens" --n-gpu-layers 99 --threads 4 --no-webui --reasoning off \
  --cache-ram "$cache_mib"
