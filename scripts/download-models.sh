#!/usr/bin/env bash
# Download the models used by config/local/qwen3-8b into one models root.
#
#   bash scripts/download-models.sh [MODELS_ROOT]      # default /workspace/models
#   SKIP_LLM=1 bash scripts/download-models.sh         # speech models only
#
# Every file is pinned by SHA256 (the files measured in the 2026-10 evaluations);
# existing files with the right hash are kept. The layout matches what
# scripts/prepare-local-config.py --models-root expects:
#
#   MODELS_ROOT/qwen3-8b/Qwen3-8B-Q4_K_M.gguf   Qwen/Qwen3-8B-GGUF (Apache-2.0)
#   MODELS_ROOT/sensevoice/                     SenseVoice int8 (STT)
#   MODELS_ROOT/supertonic/                     Supertonic 3 int8, sherpa-onnx package (TTS)
#   MODELS_ROOT/kws/                            Korean streaming zipformer + "레미야" keyword
#   MODELS_ROOT/silero_vad.onnx                 VAD
set -euo pipefail

root=${1:-/home/kyj/workspace/models}
cache=${MODEL_CACHE:-"$root/.download"}
sherpa=https://github.com/k2-fsa/sherpa-onnx/releases/download
qwen_revision=7c41481f57cb95916b40956ab2f0b139b296d974
mkdir -p "$root" "$cache"

sha() { sha256sum "$1" | cut -d' ' -f1; }

fetch() {  # url destination
  if [[ ! -s "$2" ]]; then
    echo "download $(basename "$2")"
    curl -fL --retry 3 --retry-delay 5 -C - -o "$2.part" "$1"
    mv "$2.part" "$2"
  fi
}

verify() {  # file sha256
  local actual
  actual=$(sha "$1")
  if [[ "$actual" != "$2" ]]; then
    echo "SHA256 mismatch: $1" >&2
    echo "  expected $2" >&2
    echo "  actual   $actual" >&2
    exit 1
  fi
}

install_from_archive() {  # archive-url archive-dir target-dir "name sha256"...
  local url=$1 dir=$2 target=$3
  shift 3
  local missing=0 entry name hash
  for entry in "$@"; do
    read -r name hash <<<"$entry"
    if [[ ! -f "$target/$name" ]] || [[ "$(sha "$target/$name")" != "$hash" ]]; then
      missing=1
    fi
  done
  if (( missing )); then
    local archive="$cache/$(basename "$url")"
    fetch "$url" "$archive"
    tar -xjf "$archive" -C "$cache"
    mkdir -p "$target"
    for entry in "$@"; do
      read -r name hash <<<"$entry"
      cp "$cache/$dir/$name" "$target/$name"
    done
  fi
  for entry in "$@"; do
    read -r name hash <<<"$entry"
    verify "$target/$name" "$hash"
  done
  echo "ok $(basename "$target")"
}

if [[ "${SKIP_LLM:-0}" != 1 ]]; then
  mkdir -p "$root/qwen3-8b"
  llm="$root/qwen3-8b/Qwen3-8B-Q4_K_M.gguf"
  fetch "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/$qwen_revision/Qwen3-8B-Q4_K_M.gguf" "$llm"
  verify "$llm" d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785
  echo "ok qwen3-8b"
fi

install_from_archive "$sherpa/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2" \
  sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17 "$root/sensevoice" \
  "model.int8.onnx c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51" \
  "tokens.txt f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc"

install_from_archive "$sherpa/tts-models/sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2" \
  sherpa-onnx-supertonic-3-tts-int8-2026-05-11 "$root/supertonic" \
  "duration_predictor.int8.onnx c3eb91414d5ff8a7a239b7fe9e34e7e2bf8a8140d8375ffb14718b1c639325db" \
  "text_encoder.int8.onnx c7befd5ea8c3119769e8a6c1486c4edc6a3bc8365c67621c881bbb774b9902ff" \
  "vector_estimator.int8.onnx 20cd86fa5c6effedfda0e7cffe5b0569ca401c440a0c3a1d72bf39286c0db3fd" \
  "vocoder.int8.onnx e923d60f53f95eb1ce235f1dc33ec56d9c057823c96fa6f8acf98f32b0da6152" \
  "tts.json 42078d3aef1cd43ab43021f3c54f47d2d75ceb4e75f627f118890128b06a0d09" \
  "unicode_indexer.bin 8402ca48e5189a8950138580b0fff64db6f072f24ac07cd54ba8b2fbb9883b30" \
  "voice.bin 67d5209b0ee8ce6c74105ffbe12fe6a7628aea3b4ba2fcb308a4a67938a93ce8"

install_from_archive "$sherpa/asr-models/sherpa-onnx-streaming-zipformer-korean-2024-06-16.tar.bz2" \
  sherpa-onnx-streaming-zipformer-korean-2024-06-16 "$root/kws" \
  "encoder-epoch-99-avg-1.int8.onnx 8d0b1aa24fbedd4e3948564ab7facd151b8ce9b0c48fc987c541de2de3af5697" \
  "decoder-epoch-99-avg-1.onnx b29cfb4575141e50a30a22b2c4579934f3d4f45b83c9c8c08c3aef5a3fa7abfc" \
  "joiner-epoch-99-avg-1.int8.onnx 128b80a66a1f718488af8560f9d15895109b99ff3e573f0a0130e03774ef1ced" \
  "tokens.txt 016bdf0965029263b7ad01b742366ee542ef0bef38261510e8176ff6f2e9e668" \
  "bpe.model 1491bc92c47dfda4225f5b8930fba3cfa34c3b1ccd25e7d96c630a262f3e918d"
# Wake phrase for the real-PA KWS role (Lemmy uses its own WeKWS in production).
printf '▁레 미 야 @레미야\n' > "$root/kws/keywords.txt"
verify "$root/kws/keywords.txt" bc14208630d89642f5faffaa1aa30ef2cc95fc60f2c60ba04f8866c5ef15a6ab

fetch "$sherpa/asr-models/silero_vad.onnx" "$root/silero_vad.onnx"
verify "$root/silero_vad.onnx" 9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6
echo "ok silero_vad"

echo "models ready in $root (archives cached in $cache; safe to delete)"
