#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${1:-runtime/models}"
mkdir -p "$ROOT_DIR/lora"

command -v hf >/dev/null 2>&1 || {
  echo "缺少 hf CLI，请先安装：https://huggingface.co/docs/huggingface_hub/guides/cli"
  exit 1
}

hf download Qwen/Qwen-Image-Edit-2511 \
  --revision 6f3ccc0b56e431dc6a0c2b2039706d7d26f22cb9 \
  --include "transformer/*" \
  --local-dir "$ROOT_DIR/qwen_image_edit_2511"

hf download Qwen/Qwen-Image \
  --revision 75e0b4be04f60ec59a75f475837eced720f823b6 \
  --include "text_encoder/*" \
  --include "vae/*" \
  --local-dir "$ROOT_DIR/qwen_image"

hf download Qwen/Qwen-Image-Edit \
  --revision ac7f9318f633fc4b5778c59367c8128225f1e3de \
  --include "processor/*" \
  --local-dir "$ROOT_DIR/qwen_image_edit"

hf download SanJin09/qwen-image-edit-gongbi-lora-v1 \
  --revision 327edcab37396b1b60bd4c8da2be1d7efc91527a \
  --include qwen_image_edit_2511_gongbi_lora_v1.safetensors \
  --local-dir "$ROOT_DIR/lora"

echo "模型已准备到 $ROOT_DIR"
