from __future__ import annotations

import random
from dataclasses import dataclass

import numpy as np
from PIL import Image

from model_runtime.rle import encode_mask_rle


@dataclass(slots=True)
class SegmentItem:
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    mask_rle: str


def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh

    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0

    inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _fallback_grid(width: int, height: int, crop_count: int) -> list[tuple[int, int, int, int]]:
    cols = 3
    rows = max(2, (crop_count + cols - 1) // cols)
    cell_w = width // cols
    cell_h = height // rows
    bboxes: list[tuple[int, int, int, int]] = []
    for i in range(rows):
        for j in range(cols):
            if len(bboxes) >= crop_count:
                return bboxes
            x = j * cell_w
            y = i * cell_h
            w = cell_w if j < cols - 1 else width - x
            h = cell_h if i < rows - 1 else height - y
            bboxes.append((x, y, w, h))
    return bboxes


def segment_image(
    source_image: Image.Image,
    *,
    seed: int,
    crop_count: int,
    min_area_ratio: float,
    max_area_ratio: float,
    max_overlap_iou: float,
) -> list[SegmentItem]:
    rng = random.Random(seed)
    width, height = source_image.size
    total_area = width * height

    chosen: list[tuple[int, int, int, int]] = []

    for _ in range(500):
        if len(chosen) >= crop_count:
            break

        area_ratio = rng.uniform(min_area_ratio, max_area_ratio)
        target_area = int(total_area * area_ratio)
        aspect = rng.uniform(0.6, 1.8)

        w = int((target_area * aspect) ** 0.5)
        h = max(20, int(target_area / max(w, 1)))
        w = max(20, min(w, width - 1))
        h = max(20, min(h, height - 1))

        if w >= width or h >= height:
            continue

        x = rng.randint(0, max(width - w - 1, 1))
        y = rng.randint(0, max(height - h - 1, 1))
        candidate = (x, y, w, h)

        if all(_bbox_iou(candidate, existing) <= max_overlap_iou for existing in chosen):
            chosen.append(candidate)

    if len(chosen) < crop_count:
        grid = _fallback_grid(width, height, crop_count)
        for bbox in grid:
            if len(chosen) >= crop_count:
                break
            if all(_bbox_iou(bbox, existing) <= max_overlap_iou for existing in chosen):
                chosen.append(bbox)

    if len(chosen) < crop_count:
        grid = _fallback_grid(width, height, crop_count)
        for bbox in grid:
            if len(chosen) >= crop_count:
                break
            if bbox not in chosen:
                chosen.append(bbox)

    output: list[SegmentItem] = []
    for bbox in chosen[:crop_count]:
        x, y, w, h = bbox
        mask = np.zeros((height, width), dtype=np.uint8)
        mask[y : y + h, x : x + w] = 1
        output.append(
            SegmentItem(
                bbox_x=x,
                bbox_y=y,
                bbox_w=w,
                bbox_h=h,
                mask_rle=encode_mask_rle(mask),
            )
        )

    return output
