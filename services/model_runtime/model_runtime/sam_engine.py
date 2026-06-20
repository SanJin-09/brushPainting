from __future__ import annotations

import gc
import os
from contextlib import nullcontext
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from model_runtime.modelscope_loader import download_sam3_snapshot


@dataclass
class SegmentData:
    bbox: tuple[int, int, int, int]
    mask: Image.Image
    crop: Image.Image
    confidence: float
    area_ratio: float


def _mask_to_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    coords = np.argwhere(mask)
    if len(coords) == 0:
        return None
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0)
    return int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)


def _build_segment(image_np: np.ndarray, mask: np.ndarray, confidence: float) -> SegmentData | None:
    mask_bool = np.asarray(mask, dtype=bool)
    bbox = _mask_to_bbox(mask_bool)
    if bbox is None:
        return None

    height, width = image_np.shape[:2]
    if mask_bool.shape != (height, width):
        raise RuntimeError(
            f"SAM 3 mask 尺寸不匹配: mask={mask_bool.shape}, image={(height, width)}"
        )

    x, y, bbox_width, bbox_height = bbox
    alpha = (mask_bool.astype(np.uint8) * 255)
    rgba = np.dstack((image_np, alpha))
    crop = Image.fromarray(
        rgba[y : y + bbox_height, x : x + bbox_width],
        mode="RGBA",
    )
    return SegmentData(
        bbox=bbox,
        mask=Image.fromarray(alpha, mode="L"),
        crop=crop,
        confidence=float(confidence),
        area_ratio=float(mask_bool.sum() / (height * width)),
    )


def _mock_segment(source: Image.Image, user_prompt: str) -> list[SegmentData]:
    """Mock 分割：将原图切分为 3 个固定区域，用于本地开发调试"""
    image_np = np.array(source.convert("RGB"))
    h, w = image_np.shape[:2]
    half_h, half_w = h // 2, w // 2

    mock_regions: list[tuple[tuple[int, int, int, int], float]] = [
        ((0, 0, half_w, half_h), 0.92),
        ((half_w, 0, w - half_w, half_h), 0.85),
        ((0, half_h, w, h - half_h), 0.78),
    ]

    segments: list[SegmentData] = []
    for bbox, score in mock_regions:
        x, y, bw, bh = bbox
        if bw < 8 or bh < 8:
            continue
        mask = np.zeros((h, w), dtype=bool)
        mask[y : y + bh, x : x + bw] = True
        segment = _build_segment(image_np, mask, score)
        if segment is not None:
            segments.append(segment)

    return segments


def _require_path(path: str, label: str) -> str:
    resolved = Path(path)
    if not resolved.exists():
        raise RuntimeError(f"{label} 不存在: {resolved}")
    return str(resolved)


def _resolve_sam3_checkpoint() -> str:
    configured_path = os.getenv("SAM3_CHECKPOINT_PATH", "").strip()
    if configured_path and Path(configured_path).is_file():
        return str(Path(configured_path))

    source = os.getenv("SAM3_MODEL_SOURCE", "local").strip().lower()
    if source == "local":
        if not configured_path:
            raise RuntimeError("SAM3_MODEL_SOURCE=local 时必须设置 SAM3_CHECKPOINT_PATH")
        return _require_path(configured_path, "SAM 3 权重")
    if source != "modelscope":
        raise RuntimeError(f"不支持的 SAM3_MODEL_SOURCE: {source}")

    checkpoint = download_sam3_snapshot(
        model_id=os.getenv("SAM3_MODELSCOPE_MODEL_ID", "facebook/sam3").strip(),
        revision=os.getenv("SAM3_MODELSCOPE_REVISION", "master").strip(),
        local_dir=os.getenv(
            "SAM3_MODELSCOPE_LOCAL_DIR",
            "./runtime/models/sam3",
        ).strip(),
        checkpoint_filename=os.getenv(
            "SAM3_MODELSCOPE_CHECKPOINT_FILENAME",
            "sam3.pt",
        ).strip(),
        full_snapshot=os.getenv(
            "SAM3_MODELSCOPE_DOWNLOAD_FULL",
            "false",
        ).strip().lower()
        in {"1", "true", "yes", "on"},
    )
    return str(checkpoint)


@lru_cache(maxsize=1)
def _sam3_runtime():
    import torch
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    checkpoint = _resolve_sam3_checkpoint()
    device = os.getenv("SAM3_DEVICE", "cuda").strip().lower()
    amp_dtype = os.getenv("SAM3_AMP_DTYPE", "bfloat16").strip().lower()
    if amp_dtype not in {"bfloat16", "float16", "float32"}:
        raise RuntimeError(
            f"不支持的 SAM3_AMP_DTYPE: {amp_dtype}，可选 bfloat16 / float16 / float32"
        )
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("SAM 3 配置为 CUDA 推理，但当前没有可用的 NVIDIA CUDA GPU")

    model = build_sam3_image_model(
        checkpoint_path=checkpoint,
        device=device,
        eval_mode=True,
        load_from_HF=False,
    )
    if (not device.startswith("cuda") or amp_dtype == "float32") and hasattr(
        model,
        "float",
    ):
        model.float()

    return Sam3Processor(
        model,
        device=device,
        confidence_threshold=float(os.getenv("SAM3_SCORE_THRESHOLD", "0.30")),
    )


def preload_runtime() -> None:
    backend = os.getenv("SAM3_BACKEND", "mock").strip().lower()
    preload = os.getenv("SAM3_PRELOAD", "false").strip().lower() in {"1", "true", "yes", "on"}
    if backend == "sam3" and preload:
        _sam3_runtime()
    elif backend not in {"mock", "sam3", "disabled"}:
        raise RuntimeError(f"不支持的 SAM3_BACKEND: {backend}")


def release_runtime() -> None:
    _sam3_runtime.cache_clear()
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _to_numpy(value) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if str(getattr(value, "dtype", "")) == "torch.bfloat16":
        value = value.float()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _sam3_inference_context(processor):
    device = str(getattr(processor, "device", "cpu")).lower()
    if not device.startswith("cuda"):
        return nullcontext()

    import torch

    dtype_name = os.getenv("SAM3_AMP_DTYPE", "bfloat16").strip().lower()
    dtype_by_name = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
    }
    if dtype_name == "float32":
        return nullcontext()
    if dtype_name not in dtype_by_name:
        raise RuntimeError(
            f"不支持的 SAM3_AMP_DTYPE: {dtype_name}，可选 bfloat16 / float16 / float32"
        )
    return torch.autocast(device_type="cuda", dtype=dtype_by_name[dtype_name])


def segment_image(source: Image.Image, user_prompt: str) -> list[SegmentData]:
    backend = os.getenv("SAM3_BACKEND", "mock").strip().lower()

    if backend == "mock":
        return _mock_segment(source, user_prompt)

    if backend == "disabled":
        raise RuntimeError("SAM 3 分割功能未启用")
    if backend != "sam3":
        raise RuntimeError(f"不支持的 SAM3_BACKEND: {backend}")

    processor = _sam3_runtime()
    image_np = np.array(source.convert("RGB"))
    h, w = image_np.shape[:2]
    min_area_ratio = float(os.getenv("SEGMENT_MIN_AREA_RATIO", "0.015"))
    max_results = int(os.getenv("SEGMENT_MAX_RESULTS", "12"))

    with _sam3_inference_context(processor):
        state = processor.set_image(source.convert("RGB"))
        output = processor.set_text_prompt(
            prompt=user_prompt.strip(),
            state=state,
        )
    masks = _to_numpy(output["masks"])
    scores = _to_numpy(output["scores"]).reshape(-1)
    if masks.ndim == 4 and masks.shape[1] == 1:
        masks = masks[:, 0]
    elif masks.ndim == 2:
        masks = masks[np.newaxis, ...]
    if masks.ndim != 3:
        raise RuntimeError(f"SAM 3 返回了无法识别的 mask 形状: {masks.shape}")
    if len(masks) != len(scores):
        raise RuntimeError(
            f"SAM 3 返回的 mask 与 score 数量不一致: masks={len(masks)}, scores={len(scores)}"
        )

    segments: list[SegmentData] = []
    for mask, score in zip(masks, scores):
        segment = _build_segment(image_np, mask, float(score))
        if segment is None or segment.area_ratio < min_area_ratio:
            continue
        segments.append(segment)

    segments.sort(key=lambda s: s.confidence, reverse=True)
    segments = segments[:max_results]
    segments.sort(key=lambda s: s.area_ratio, reverse=True)
    return segments
