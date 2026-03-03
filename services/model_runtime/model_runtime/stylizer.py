from __future__ import annotations

import os

import numpy as np
import cv2
from PIL import Image


def _to_cv_rgb(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("RGB"))


def _to_pil(image: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(image, 0, 255).astype(np.uint8), mode="RGB")


def style_crop(
    crop_image: Image.Image,
    crop_mask: np.ndarray,
    *,
    seed: int,
    controlnet_weight: float,
) -> Image.Image:
    backend = os.getenv("MODEL_BACKEND", "mock").lower()
    if backend == "diffusers":
        from model_runtime.diffusers_backend import style_crop_diffusers

        return style_crop_diffusers(
            crop_image,
            crop_mask,
            seed=seed,
            controlnet_weight=controlnet_weight,
        )

    _ = seed
    rgb = _to_cv_rgb(crop_image)
    smooth = cv2.bilateralFilter(rgb, 9, 50, 50)

    hsv = cv2.cvtColor(smooth, cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * 0.75, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * 1.02, 0, 255)
    toned = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    quant = (toned // 32) * 32

    gray = cv2.cvtColor(quant, cv2.COLOR_RGB2GRAY)
    e1 = cv2.Canny(gray, 80, 160)
    e2 = cv2.dilate(e1, np.ones((2, 2), np.uint8), iterations=1)
    edges = (e2 > 0).astype(np.uint8)

    line_strength = np.clip(controlnet_weight, 0.3, 1.0)
    result = quant.astype(np.float32)
    ink = np.array([45, 32, 24], dtype=np.float32)
    result[edges > 0] = result[edges > 0] * (1.0 - 0.8 * line_strength) + ink * (0.8 * line_strength)

    paper_noise = np.random.default_rng(seed).normal(0, 4, size=result.shape).astype(np.float32)
    result = np.clip(result + paper_noise, 0, 255)

    pil_rgb = _to_pil(result)

    alpha = (crop_mask.astype(np.uint8) * 255)
    rgba = pil_rgb.convert("RGBA")
    rgba_np = np.array(rgba)
    rgba_np[..., 3] = alpha
    return Image.fromarray(rgba_np, mode="RGBA")
