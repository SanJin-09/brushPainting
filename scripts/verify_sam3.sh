#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKPOINT="${SAM3_CHECKPOINT_PATH:-$ROOT/runtime/models/sam3/sam3.pt}"
INPUT_IMAGE="${1:-$ROOT/runtime/sam3_verify_input.png}"
VERIFY_PROMPT="${2:-object}"

echo "======================================================================"
echo " SAM3 GPU 验证全流程"
echo "  项目根目录: $ROOT"
echo "  Checkpoint: $CHECKPOINT"
echo "  测试图片: $INPUT_IMAGE"
echo "  提示词: $VERIFY_PROMPT"
echo "======================================================================"

test -f "$CHECKPOINT" || {
    echo "缺少 SAM 3 权重: $CHECKPOINT"
    exit 1
}
test -f "$INPUT_IMAGE" || {
    echo "缺少测试图片。用法: scripts/verify_sam3.sh /path/to/image.png [text-prompt]"
    exit 1
}

# ── Step 1: 安装项目模型依赖 ────────────────────────────────
echo ""
echo "[Step 1/5] 安装 Python 依赖 …"
pip install \
    --index-url https://download.pytorch.org/whl/cu126 \
    torch==2.7.0 torchvision==0.22.0 -q
pip install -r "$ROOT/services/model_runtime/requirements-sam3.txt" -q
echo "  ✓ 完成"

# ── Step 2: 检查仓库内置 sam3 包 ─────────────────────────────
echo ""
echo "[Step 2/5] 检查内置 sam3 包 …"
PYTHONPATH="$ROOT/services/model_runtime" python -c "import sam3; print(f'  ✓ sam3 {sam3.__version__}')"

# ── Step 3: CUDA 检查 ────────────────────────────────────────
echo ""
echo "[Step 3/5] CUDA 环境 …"
python -c "import torch; print(f'  PyTorch: {torch.__version__}'); print(f'  CUDA:    {torch.cuda.is_available()}'); print(f'  GPU:     {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# ── Step 4: 加载 SAM3 模型 ───────────────────────────────────
echo ""
echo "[Step 4/5] 加载 SAM3 模型 …"
export SAM3_BACKEND=sam3
export SAM3_PRELOAD=true
export SAM3_MODEL_SOURCE=local
export SAM3_CHECKPOINT_PATH="$CHECKPOINT"
export SAM3_DEVICE=cuda
export SAM3_AMP_DTYPE="${SAM3_AMP_DTYPE:-bfloat16}"
export VERIFY_PROMPT

cd "$ROOT/services/model_runtime"
python -c "
from model_runtime.sam_engine import _sam3_runtime
p = _sam3_runtime()
print('  ✓ SAM3 模型加载成功')
"

# ── Step 5: 推理测试 ─────────────────────────────────────────
echo ""
echo "[Step 5/5] 推理测试 …"
python -c "
from PIL import Image
from model_runtime.sam_engine import segment_image
import os

image_path = '$INPUT_IMAGE'
img = Image.open(image_path).convert('RGB')
segs = segment_image(img, os.environ['VERIFY_PROMPT'])
print(f'  ✓ 检测到 {len(segs)} 个区域:')
for i, s in enumerate(segs):
    print(f'    [{i}] bbox={s.bbox}  area={s.area_ratio:.4f}  conf={s.confidence:.3f}')
"

echo ""
echo "======================================================================"
echo " 全部通过 ✓"
echo "======================================================================"
