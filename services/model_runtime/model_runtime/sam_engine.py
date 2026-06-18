from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image


@dataclass
class SegmentData:
    bbox: tuple[int, int, int, int]
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


def _mock_segment(source: Image.Image, user_prompt: str) -> list[SegmentData]:
    """Mock 分割：将原图切分为 3 个固定区域，用于本地开发调试"""
    image_np = np.array(source.convert("RGB"))
    h, w = image_np.shape[:2]
    total_area = h * w
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
        crop = Image.fromarray(image_np[y:y + bh, x:x + bw])
        area_ratio = float((bw * bh) / total_area)
        segments.append(SegmentData(
            bbox=bbox,
            crop=crop,
            confidence=score,
            area_ratio=area_ratio,
        ))

    return segments


def _require_path(path: str, label: str) -> str:
    resolved = Path(path)
    if not resolved.exists():
        raise RuntimeError(f"{label} 不存在: {resolved}")
    return str(resolved)


@lru_cache(maxsize=1)
def _sam3_runtime():
    import torch
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    checkpoint = _require_path(os.environ["SAM3_CHECKPOINT_PATH"], "SAM 3 权重")
    if not torch.cuda.is_available():
        raise RuntimeError("SAM 3 推理需要可用的 NVIDIA CUDA GPU")

    model = build_sam3_image_model(checkpoint)
    device = os.getenv("SAM3_DEVICE", "cuda")
    model.to(device)
    model.eval()

    return Sam3Processor(
        model,
        score_threshold=float(os.getenv("SAM3_SCORE_THRESHOLD", "0.30")),
    )


def preload_runtime() -> None:
    backend = os.getenv("MODEL_BACKEND", "mock").strip().lower()
    if backend == "diffsynth_qwen":
        _sam3_runtime()
    elif backend != "mock":
        raise RuntimeError(f"不支持的 MODEL_BACKEND: {backend}")


def segment_image(source: Image.Image, user_prompt: str) -> list[SegmentData]:
    backend = os.getenv("MODEL_BACKEND", "mock").strip().lower()

    if backend == "mock":
        return _mock_segment(source, user_prompt)

    if backend != "diffsynth_qwen":
        raise RuntimeError(f"不支持的 MODEL_BACKEND: {backend}")

    processor = _sam3_runtime()
    image_np = np.array(source.convert("RGB"))
    h, w = image_np.shape[:2]
    total_area = h * w
    min_area_ratio = float(os.getenv("SEGMENT_MIN_AREA_RATIO", "0.015"))
    max_results = int(os.getenv("SEGMENT_MAX_RESULTS", "12"))

    processor.set_image(source)
    masks, scores, _ = processor.predict(
        text_prompt=user_prompt.strip(),
        multimask_output=False,
    )

    segments: list[SegmentData] = []
    for mask, score in zip(masks, scores):
        mask_bool = mask.astype(bool)
        area_ratio = float(mask_bool.sum() / total_area)
        if area_ratio < min_area_ratio:
            continue

        bbox = _mask_to_bbox(mask_bool)
        if bbox is None:
            continue

        x, y, bw, bh = bbox
        crop = Image.fromarray(image_np[y:y + bh, x:x + bw])

        segments.append(SegmentData(
            bbox=bbox,
            crop=crop,
            confidence=float(score),
            area_ratio=area_ratio,
        ))

    segments.sort(key=lambda s: s.confidence, reverse=True)
    segments = segments[:max_results]
    segments.sort(key=lambda s: s.area_ratio, reverse=True)
    return segments
