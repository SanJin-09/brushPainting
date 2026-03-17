from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from model_runtime.style_config import StyleConfigError, load_style_config


class ZImageBackendUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _check_imports() -> None:
    try:
        import accelerate  # noqa: F401
        import diffusers  # noqa: F401
        import safetensors  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception as exc:
        raise ZImageBackendUnavailable(
            "Z-Image backend is enabled but required packages are missing. "
            "Install torch + diffusers + transformers + accelerate + safetensors."
        ) from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _model_device() -> str:
    return os.getenv("MODEL_DEVICE", "cuda").strip().lower()


def _torch_dtype(torch_module):
    precision = os.getenv("MODEL_PRECISION", "bf16").strip().lower()
    if not _model_device().startswith("cuda") and precision in {"fp16", "float16", "half", "bf16", "bfloat16"}:
        return torch_module.float32
    if precision in {"bf16", "bfloat16"}:
        return torch_module.bfloat16
    if precision in {"fp16", "float16", "half"}:
        return torch_module.float16
    if precision in {"fp32", "float32"}:
        return torch_module.float32
    return torch_module.bfloat16


def _align_dim(value: int, multiple: int = 16) -> int:
    if value <= 0:
        return multiple
    rounded = int(round(value / multiple)) * multiple
    return max(multiple, rounded)


def _resize_pair_for_model(
    image: Image.Image,
    mask: Image.Image | None,
    *,
    target_long_side: int,
    min_short_side: int,
) -> tuple[Image.Image, Image.Image | None]:
    width, height = image.size
    long_side = max(width, height)
    short_side = min(width, height)
    scale = 1.0

    if long_side > target_long_side > 0:
        scale = target_long_side / long_side
    elif short_side < min_short_side and min_short_side > 0:
        scale = min_short_side / short_side

    if abs(scale - 1.0) < 1e-6:
        return image, mask

    new_w = _align_dim(int(round(width * scale)))
    new_h = _align_dim(int(round(height * scale)))
    resized_image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    resized_mask = None
    if mask is not None:
        resized_mask = mask.resize((new_w, new_h), Image.Resampling.NEAREST)
    return resized_image, resized_mask


@lru_cache(maxsize=1)
def _style_payload() -> dict[str, Any]:
    style_config_path = os.getenv("STYLE_CONFIG_PATH", "/app/configs/styles/gongbi_default.yaml")
    try:
        return load_style_config(style_config_path)
    except StyleConfigError as exc:
        raise ZImageBackendUnavailable(str(exc)) from exc


def _payload_render_value(payload: dict[str, Any], key: str) -> Any | None:
    render = payload.get("render")
    if not isinstance(render, dict):
        return None
    return render.get(key)


def _resolve_model_path(payload: dict[str, Any]) -> Path:
    override = os.getenv("Z_IMAGE_MODEL_PATH")
    if override:
        return Path(override)

    models = payload.get("models")
    if isinstance(models, dict):
        configured = models.get("z_image_model_path")
        if configured:
            return Path(configured)

    model_root = Path(os.getenv("MODEL_ROOT", "/models"))
    return model_root / "z_image"


def _resolve_prompts(payload: dict[str, Any]) -> tuple[str, str]:
    profile = payload.get("prompt_profile")
    if not isinstance(profile, dict):
        return ("Traditional Chinese gongbi painting", "")

    positive = str(profile.get("positive", "")).strip() or "Traditional Chinese gongbi painting"
    negative = str(profile.get("negative", "")).strip()
    return positive, negative


def _resolve_steps(payload: dict[str, Any]) -> int:
    configured = _payload_render_value(payload, "z_image_steps")
    try:
        configured_int = int(configured)
    except (TypeError, ValueError):
        configured_int = 32
    return _env_int("Z_IMAGE_STEPS", configured_int)


def _resolve_size(payload: dict[str, Any]) -> int:
    configured = _payload_render_value(payload, "z_image_size")
    try:
        configured_int = int(configured)
    except (TypeError, ValueError):
        configured_int = 1536
    return _env_int("Z_IMAGE_SIZE", configured_int)


def _resolve_cfg(payload: dict[str, Any]) -> float:
    configured = _payload_render_value(payload, "z_image_cfg")
    try:
        configured_value = float(configured)
    except (TypeError, ValueError):
        configured_value = 4.0
    return _env_float("Z_IMAGE_CFG", configured_value)


def _resolve_img2img_strength(payload: dict[str, Any]) -> float:
    configured = _payload_render_value(payload, "z_image_img2img_strength")
    try:
        configured_value = float(configured)
    except (TypeError, ValueError):
        configured_value = 0.6
    return float(np.clip(_env_float("Z_IMAGE_IMG2IMG_STRENGTH", configured_value), 0.0, 1.0))


def _resolve_inpaint_strength(payload: dict[str, Any]) -> float:
    configured = _payload_render_value(payload, "z_image_inpaint_strength")
    try:
        configured_value = float(configured)
    except (TypeError, ValueError):
        configured_value = 1.0
    return float(np.clip(_env_float("Z_IMAGE_INPAINT_STRENGTH", configured_value), 0.0, 1.0))


def _ensure_model_exists(path: Path, name: str) -> Path:
    if path.exists():
        return path
    raise ZImageBackendUnavailable(
        f"{name} not found at {path}. "
        "Please mount Tongyi-MAI/Z-Image weights and check STYLE_CONFIG_PATH."
    )


def _pretrained_kwargs(path: Path, *, torch_dtype) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "torch_dtype": torch_dtype,
        "local_files_only": True,
        "low_cpu_mem_usage": False,
    }
    if any(path.rglob("*.safetensors")):
        kwargs["use_safetensors"] = True
    return kwargs


def _prepare_pipeline(pipe, torch_module):
    device = _model_device()
    if device.startswith("cuda"):
        if not torch_module.cuda.is_available():
            raise ZImageBackendUnavailable("MODEL_DEVICE is cuda but torch.cuda is unavailable")
        pipe.to("cuda")
    else:
        pipe.to(device)

    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass
    try:
        pipe.set_progress_bar_config(disable=True)
    except Exception:
        pass


def _make_generator(torch_module, seed: int):
    device = "cuda" if _model_device().startswith("cuda") else "cpu"
    return torch_module.Generator(device=device).manual_seed(int(seed))


def _pipeline_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    _positive_prompt, negative_prompt = _resolve_prompts(payload)
    cfg = _resolve_cfg(payload)
    kwargs: dict[str, Any] = {
        "num_inference_steps": _resolve_steps(payload),
        "guidance_scale": cfg,
    }
    if cfg > 1.0 and negative_prompt:
        kwargs["negative_prompt"] = negative_prompt
    return kwargs


@lru_cache(maxsize=1)
def _style_runtime():
    _check_imports()
    import torch
    from diffusers import ZImageImg2ImgPipeline

    payload = _style_payload()
    model_path = _ensure_model_exists(_resolve_model_path(payload), "Z-Image model")
    dtype = _torch_dtype(torch)

    pipe = ZImageImg2ImgPipeline.from_pretrained(
        str(model_path),
        **_pretrained_kwargs(model_path, torch_dtype=dtype),
    )

    _prepare_pipeline(pipe, torch)
    prompts = _resolve_prompts(payload)
    return pipe, prompts, torch, payload


@lru_cache(maxsize=1)
def _inpaint_runtime():
    _check_imports()
    import torch
    from diffusers import ZImageInpaintPipeline

    payload = _style_payload()
    model_path = _ensure_model_exists(_resolve_model_path(payload), "Z-Image model")
    dtype = _torch_dtype(torch)

    pipe = ZImageInpaintPipeline.from_pretrained(
        str(model_path),
        **_pretrained_kwargs(model_path, torch_dtype=dtype),
    )

    _prepare_pipeline(pipe, torch)
    prompts = _resolve_prompts(payload)
    return pipe, prompts, torch, payload


def _soft_blend(base_patch: np.ndarray, edit_patch: np.ndarray, mask_patch: np.ndarray, *, feather: int) -> np.ndarray:
    alpha = (mask_patch.astype(np.float32) > 0).astype(np.float32)
    if feather > 0:
        ksize = feather * 2 + 1
        alpha = cv2.GaussianBlur(alpha, (ksize, ksize), sigmaX=max(feather / 2, 1), sigmaY=max(feather / 2, 1))
        alpha = np.clip(alpha, 0.0, 1.0)
    alpha3 = alpha[:, :, None]
    return np.clip(edit_patch * alpha3 + base_patch * (1.0 - alpha3), 0, 255).astype(np.uint8)


def style_image_zimage(
    source_image: Image.Image,
    *,
    seed: int,
    controlnet_weight: float,
) -> Image.Image:
    _ = controlnet_weight
    pipe, prompts, torch_module, payload = _style_runtime()
    positive_prompt, _negative_prompt = prompts

    original_size = source_image.size
    image_rgb = source_image.convert("RGB")

    model_input, _ = _resize_pair_for_model(
        image_rgb,
        None,
        target_long_side=_resolve_size(payload),
        min_short_side=512,
    )

    kwargs = _pipeline_kwargs(payload)
    kwargs.update(
        {
            "prompt": positive_prompt,
            "image": model_input,
            "strength": _resolve_img2img_strength(payload),
            "generator": _make_generator(torch_module, seed),
        }
    )

    result = pipe(**kwargs).images[0].convert("RGB")
    return result.resize(original_size, Image.Resampling.LANCZOS)


def inpaint_region_zimage(
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
) -> Image.Image:
    _ = controlnet_weight
    pipe, prompts, torch_module, payload = _inpaint_runtime()
    positive_prompt, _negative_prompt = prompts
    prompt = positive_prompt
    if prompt_override:
        prompt = f"{prompt}, {prompt_override}"

    current_rgb = current_image.convert("RGB")
    _ = source_image.convert("RGB")
    width, height = current_rgb.size

    x0 = max(0, bbox_x - context_pad)
    y0 = max(0, bbox_y - context_pad)
    x1 = min(width, bbox_x + bbox_w + context_pad)
    y1 = min(height, bbox_y + bbox_h + context_pad)

    patch = current_rgb.crop((x0, y0, x1, y1)).convert("RGB")

    mask_patch = (mask[y0:y1, x0:x1].astype(np.uint8) > 0).astype(np.uint8) * 255
    mask_image = Image.fromarray(mask_patch, mode="L")

    run_patch, run_mask = _resize_pair_for_model(
        patch,
        mask_image,
        target_long_side=_resolve_size(payload),
        min_short_side=512,
    )
    assert run_mask is not None

    kwargs = _pipeline_kwargs(payload)
    kwargs.update(
        {
            "prompt": prompt,
            "image": run_patch,
            "mask_image": run_mask,
            "strength": _resolve_inpaint_strength(payload),
            "generator": _make_generator(torch_module, seed),
        }
    )

    refined = pipe(**kwargs).images[0].convert("RGB")
    refined = refined.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)

    patch_np = np.array(patch, dtype=np.uint8)
    refined_np = np.array(refined, dtype=np.uint8)
    mask_resized = np.array(mask_image.resize((x1 - x0, y1 - y0), Image.Resampling.NEAREST), dtype=np.uint8)
    blended_patch = _soft_blend(patch_np.astype(np.float32), refined_np.astype(np.float32), mask_resized, feather=mask_feather)

    full_np = np.array(current_rgb, dtype=np.uint8)
    full_np[y0:y1, x0:x1] = blended_patch
    return Image.fromarray(full_np, mode="RGB")
