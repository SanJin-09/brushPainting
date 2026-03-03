from __future__ import annotations

from dataclasses import dataclass
import os

import cv2
import numpy as np
from PIL import Image

from model_runtime.rle import decode_mask_rle


@dataclass(slots=True)
class Layer:
    image: Image.Image
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    mask_rle: str


def _paste_rgba(canvas: Image.Image, layer: Layer) -> None:
    layer_img = layer.image.resize((layer.bbox_w, layer.bbox_h), Image.Resampling.LANCZOS)
    canvas.alpha_composite(layer_img, (layer.bbox_x, layer.bbox_y))


def _build_boundary_band(height: int, width: int, masks: list[np.ndarray]) -> np.ndarray:
    full = np.zeros((height, width), dtype=np.uint8)
    for mask in masks:
        full = np.maximum(full, mask.astype(np.uint8))

    dilated = cv2.dilate(full, np.ones((32, 32), np.uint8), iterations=1)
    eroded = cv2.erode(full, np.ones((16, 16), np.uint8), iterations=1)
    band = cv2.subtract(dilated, eroded)
    return (band > 0).astype(np.uint8)


def compose_with_seam_refine(source: Image.Image, layers: list[Layer], seam_pass_count: int = 1) -> Image.Image:
    backend = os.getenv("MODEL_BACKEND", "mock").lower()
    if backend == "diffusers":
        from model_runtime.diffusers_backend import seam_inpaint_diffusers

        composed = source.convert("RGB")
        return seam_inpaint_diffusers(composed, layers, seam_pass_count=seam_pass_count)

    base = source.convert("RGBA")
    width, height = base.size

    for layer in layers:
        _paste_rgba(base, layer)

    merged = np.array(base.convert("RGB"), dtype=np.float32)

    masks = [decode_mask_rle(layer.mask_rle) for layer in layers]
    boundary = _build_boundary_band(height, width, masks)

    for _ in range(max(1, seam_pass_count)):
        blurred = cv2.GaussianBlur(merged, (0, 0), sigmaX=1.5, sigmaY=1.5)
        bilateral = cv2.bilateralFilter(blurred.astype(np.uint8), d=7, sigmaColor=35, sigmaSpace=35).astype(np.float32)
        mask3 = np.stack([boundary] * 3, axis=-1)
        merged = np.where(mask3 > 0, 0.6 * bilateral + 0.4 * merged, merged)

    merged = np.clip(merged, 0, 255).astype(np.uint8)
    return Image.fromarray(merged, mode="RGB")
