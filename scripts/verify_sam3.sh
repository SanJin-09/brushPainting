#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKPOINT="${SAM3_CHECKPOINT_PATH:-$ROOT/runtime/models/sam3/sam3.pt}"

echo "======================================================================"
echo " SAM3 GPU 验证全流程"
echo "  项目根目录: $ROOT"
echo "  Checkpoint: $CHECKPOINT"
echo "======================================================================"

# ── Step 1: 安装基础依赖 ────────────────────────────────────
echo ""
echo "[Step 1/5] 安装 Python 依赖 …"
pip install torch torchvision Pillow numpy -q
echo "  ✓ 完成"

# ── Step 2: 安装 sam3 包 ─────────────────────────────────────
echo ""
echo "[Step 2/5] 安装 sam3 包 …"
SAM3_DIR=/tmp/sam3_$$_
if python -c "import sam3" 2>/dev/null; then
    echo "  ✓ sam3 已安装"
else
    echo "  正在克隆 (--depth 1) …"
    git clone --depth 1 https://gitclone.com/github.com/facebookresearch/sam3.git "$SAM3_DIR" 2>&1 | tail -1
    echo "  正在安装 …"
    cd "$SAM3_DIR" && pip install . -q 2>&1 | tail -3
    cd "$ROOT"
    rm -rf "$SAM3_DIR"
    echo "  ✓ sam3 安装完成"
fi

# ── Step 3: CUDA 检查 ────────────────────────────────────────
echo ""
echo "[Step 3/5] CUDA 环境 …"
python -c "import torch; print(f'  PyTorch: {torch.__version__}'); print(f'  CUDA:    {torch.cuda.is_available()}'); print(f'  GPU:     {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"

# ── Step 4: 加载 SAM3 模型 ───────────────────────────────────
echo ""
echo "[Step 4/5] 加载 SAM3 模型 …"
export MODEL_BACKEND=diffsynth_qwen
export SAM3_CHECKPOINT_PATH="$CHECKPOINT"
export SAM3_DEVICE=cuda

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

img = Image.new('RGB', (512, 512), 'red')
segs = segment_image(img, 'everything')
print(f'  ✓ 检测到 {len(segs)} 个区域:')
for i, s in enumerate(segs):
    print(f'    [{i}] bbox={s.bbox}  area={s.area_ratio:.4f}  conf={s.confidence:.3f}')
"

echo ""
echo "======================================================================"
echo " 全部通过 ✓"
echo "======================================================================"
