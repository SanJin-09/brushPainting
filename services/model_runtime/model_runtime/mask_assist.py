from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from model_runtime.rle import encode_mask_rle


@dataclass
class MaskAssistResult:
    mask_rle: str
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int


def _bbox_from_mask(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        raise ValueError("mask is empty")
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max()) + 1
    y1 = int(ys.max()) + 1
    return x0, y0, x1 - x0, y1 - y0


def _largest_component(mask: np.ndarray) -> np.ndarray:
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if component_count <= 1:
        return mask.astype(np.uint8)

    best_idx = 1
    best_area = int(stats[1, cv2.CC_STAT_AREA])
    for idx in range(2, component_count):
        area = int(stats[idx, cv2.CC_STAT_AREA])
        if area > best_area:
            best_area = area
            best_idx = idx
    return (labels == best_idx).astype(np.uint8)


def _mock_refine(mask: np.ndarray) -> np.ndarray:
    refined = (mask.astype(np.uint8) > 0).astype(np.uint8)
    refined = cv2.morphologyEx(refined, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=1)
    refined = cv2.morphologyEx(refined, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), iterations=1)
    refined = cv2.dilate(refined, np.ones((5, 5), np.uint8), iterations=1)
    return _largest_component(refined)


def _infer_sam_model_type(path: Path) -> str:
    name = path.name.lower()
    if "vit_h" in name:
        return "vit_h"
    if "vit_l" in name:
        return "vit_l"
    return "vit_b"


@lru_cache(maxsize=1)
def _sam_runtime():
    model_path = Path(os.getenv("SAM_MODEL_PATH", "./runtime/models/sam/sam_vit_b.pth"))
    if not model_path.exists():
        raise RuntimeError(f"SAM model not found: {model_path}")

    try:
        import torch
        from segment_anything import SamPredictor, sam_model_registry
    except Exception as exc:
        raise RuntimeError("SAM backend requires the segment-anything package") from exc

    model_type = _infer_sam_model_type(model_path)
    device = "cuda" if os.getenv("MODEL_DEVICE", "cpu").startswith("cuda") and torch.cuda.is_available() else "cpu"
    sam = sam_model_registry[model_type](checkpoint=str(model_path))
    sam.to(device=device)
    predictor = SamPredictor(sam)
    return predictor


def _sam_refine(image: Image.Image, mask: np.ndarray) -> np.ndarray:
    predictor = _sam_runtime()
    rgb = np.array(image.convert("RGB"))
    predictor.set_image(rgb)

    bbox_x, bbox_y, bbox_w, bbox_h = _bbox_from_mask(mask)
    box = np.array([bbox_x, bbox_y, bbox_x + bbox_w, bbox_y + bbox_h], dtype=np.float32)
    masks, _, _ = predictor.predict(box=box, multimask_output=False)
    refined = (masks[0].astype(np.uint8) > 0).astype(np.uint8)
    return _largest_component(refined)


def refine_mask(image: Image.Image, mask: np.ndarray) -> MaskAssistResult:
    backend = os.getenv("MASK_ASSIST_BACKEND", "mock").strip().lower()
    binary_mask = (mask.astype(np.uint8) > 0).astype(np.uint8)
    if int(binary_mask.sum()) == 0:
        raise ValueError("mask is empty")

    if backend == "sam":
        refined = _sam_refine(image, binary_mask)
    else:
        refined = _mock_refine(binary_mask)

    bbox_x, bbox_y, bbox_w, bbox_h = _bbox_from_mask(refined)
    return MaskAssistResult(
        mask_rle=encode_mask_rle(refined),
        bbox_x=bbox_x,
        bbox_y=bbox_y,
        bbox_w=bbox_w,
        bbox_h=bbox_h,
    )
