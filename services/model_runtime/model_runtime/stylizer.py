from __future__ import annotations

from collections.abc import Callable
import hashlib
import os

import cv2
import numpy as np
from PIL import Image

ProgressCallback = Callable[[int, int, str], None]
QWEN_LOCAL_EDIT_UNSUPPORTED_ERROR = "Qwen backend does not support local masked edit in this deployment"


def _to_cv_rgb(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("RGB"))


def _to_pil(image: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(image, 0, 255).astype(np.uint8), mode="RGB")


def _stylize_rgb(rgb: np.ndarray, *, seed: int, controlnet_weight: float) -> np.ndarray:
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
    return np.clip(result + paper_noise, 0, 255)


def _apply_prompt_hint(image: np.ndarray, prompt_override: str | None) -> np.ndarray:
    if not prompt_override:
        return image

    digest = hashlib.sha256(prompt_override.encode("utf-8")).digest()
    sat_gain = 0.88 + (digest[0] / 255.0) * 0.18
    value_gain = 0.92 + (digest[1] / 255.0) * 0.16
    hue_shift = int(digest[2]) % 12 - 6

    hsv = cv2.cvtColor(image.astype(np.uint8), cv2.COLOR_RGB2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + hue_shift) % 180
    hsv[..., 1] = np.clip(hsv[..., 1] * sat_gain, 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * value_gain, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB).astype(np.float32)


def _soft_blend(
    base_patch: np.ndarray,
    edit_patch: np.ndarray,
    mask_patch: np.ndarray,
    *,
    feather: int,
) -> np.ndarray:
    alpha = (mask_patch.astype(np.float32) > 0).astype(np.float32)
    if feather > 0:
        ksize = feather * 2 + 1
        alpha = cv2.GaussianBlur(alpha, (ksize, ksize), sigmaX=max(feather / 2, 1), sigmaY=max(feather / 2, 1))
        alpha = np.clip(alpha, 0.0, 1.0)
    alpha3 = alpha[:, :, None]
    return np.clip(edit_patch * alpha3 + base_patch * (1.0 - alpha3), 0, 255).astype(np.uint8)


def style_image(
    source_image: Image.Image,
    *,
    seed: int,
    controlnet_weight: float,
    progress_callback: ProgressCallback | None = None,
) -> Image.Image:
    backend = os.getenv("MODEL_BACKEND", "qwen_image").lower()
    if backend == "qwen_image":
        from model_runtime.qwen_image_backend import style_image_qwen

        return style_image_qwen(
            source_image,
            seed=seed,
            controlnet_weight=controlnet_weight,
            progress_callback=progress_callback,
        )
    if backend == "zimage":
        from model_runtime.zimage_backend import style_image_zimage

        return style_image_zimage(
            source_image,
            seed=seed,
            controlnet_weight=controlnet_weight,
            progress_callback=progress_callback,
        )
    if backend != "mock":
        raise RuntimeError(f"Unsupported MODEL_BACKEND: {backend}")

    if progress_callback is not None:
        progress_callback(1, 2, "正在生成整图")
    rgb = _to_cv_rgb(source_image)
    styled = _stylize_rgb(rgb, seed=seed, controlnet_weight=controlnet_weight)
    if progress_callback is not None:
        progress_callback(2, 2, "正在生成整图")
    return _to_pil(styled)


def inpaint_region(
    current_image: Image.Image,
    source_image: Image.Image,
    mask: np.ndarray,
    *,
    bbox_x: int,
    bbox_y: int,
    bbox_w: int,
    bbox_h: int,
    seed: int,
    controlnet_weight: float,
    context_pad: int,
    mask_feather: int,
    prompt_override: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Image.Image:
    backend = os.getenv("MODEL_BACKEND", "qwen_image").lower()
    if backend == "qwen_image":
        raise RuntimeError(QWEN_LOCAL_EDIT_UNSUPPORTED_ERROR)
    if backend == "zimage":
        from model_runtime.zimage_backend import inpaint_region_zimage

        return inpaint_region_zimage(
            current_image,
            source_image,
            mask,
            bbox_x=bbox_x,
            bbox_y=bbox_y,
            bbox_w=bbox_w,
            bbox_h=bbox_h,
            seed=seed,
            controlnet_weight=controlnet_weight,
            context_pad=context_pad,
            mask_feather=mask_feather,
            prompt_override=prompt_override,
            progress_callback=progress_callback,
        )
    if backend != "mock":
        raise RuntimeError(f"Unsupported MODEL_BACKEND: {backend}")

    current_rgb = _to_cv_rgb(current_image)
    source_rgb = _to_cv_rgb(source_image)
    height, width = current_rgb.shape[:2]

    x0 = max(0, bbox_x - context_pad)
    y0 = max(0, bbox_y - context_pad)
    x1 = min(width, bbox_x + bbox_w + context_pad)
    y1 = min(height, bbox_y + bbox_h + context_pad)

    current_patch = current_rgb[y0:y1, x0:x1]
    source_patch = source_rgb[y0:y1, x0:x1]
    mask_patch = (mask[y0:y1, x0:x1].astype(np.uint8) > 0).astype(np.uint8)

    if progress_callback is not None:
        progress_callback(1, 2, "正在生成局部候选")
    edited_patch = _stylize_rgb(source_patch, seed=seed, controlnet_weight=controlnet_weight)
    edited_patch = _apply_prompt_hint(edited_patch, prompt_override)
    blended_patch = _soft_blend(current_patch.astype(np.float32), edited_patch.astype(np.float32), mask_patch, feather=mask_feather)
    if progress_callback is not None:
        progress_callback(2, 2, "正在生成局部候选")

    composed = current_rgb.copy()
    composed[y0:y1, x0:x1] = blended_patch
    return _to_pil(composed)
