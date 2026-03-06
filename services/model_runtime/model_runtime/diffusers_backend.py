from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from model_runtime.rle import decode_mask_rle
from model_runtime.style_config import StyleConfigError, load_style_config


class DiffusersBackendUnavailable(RuntimeError):
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
        raise DiffusersBackendUnavailable(
            "Diffusers backend is enabled but required packages are missing. "
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
    precision = os.getenv("MODEL_PRECISION", "fp16").strip().lower()
    if not _model_device().startswith("cuda") and precision in {"fp16", "float16", "half", "bf16", "bfloat16"}:
        return torch_module.float32
    if precision in {"fp16", "float16", "half"}:
        return torch_module.float16
    if precision in {"bf16", "bfloat16"}:
        return torch_module.bfloat16
    if precision in {"fp32", "float32"}:
        return torch_module.float32
    return torch_module.float16


def _align_dim(value: int, multiple: int = 8) -> int:
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


def _build_canny_control(image: Image.Image) -> Image.Image:
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, threshold1=100, threshold2=220)
    edges = cv2.dilate(edges, np.ones((2, 2), dtype=np.uint8), iterations=1)
    control = np.stack([edges] * 3, axis=-1)
    return Image.fromarray(control.astype(np.uint8), mode="RGB")


@lru_cache(maxsize=1)
def _style_payload() -> dict[str, Any]:
    style_config_path = os.getenv("STYLE_CONFIG_PATH", "/app/configs/styles/gongbi_default.yaml")
    try:
        return load_style_config(style_config_path)
    except StyleConfigError as exc:
        raise DiffusersBackendUnavailable(str(exc)) from exc


def _resolve_base_model_path(payload: dict[str, Any]) -> Path:
    override = os.getenv("SDXL_BASE_MODEL_PATH")
    if override:
        return Path(override)

    models = payload.get("models")
    if isinstance(models, dict):
        configured = models.get("sdxl_base_path")
        if configured:
            return Path(configured)

    model_root = Path(os.getenv("MODEL_ROOT", "/models"))
    return model_root / "sdxl" / "base"


def _resolve_inpaint_model_path(payload: dict[str, Any]) -> Path:
    override = os.getenv("SDXL_INPAINT_MODEL_PATH")
    if override:
        return Path(override)

    models = payload.get("models")
    if isinstance(models, dict):
        configured = models.get("sdxl_inpaint_path")
        if configured:
            return Path(configured)

    model_root = Path(os.getenv("MODEL_ROOT", "/models"))
    return model_root / "sdxl" / "inpaint"


def _resolve_controlnet_path(payload: dict[str, Any]) -> Path:
    override = os.getenv("SDXL_CONTROLNET_CANNY_PATH")
    if override:
        return Path(override)

    controlnet_cfg = payload.get("controlnet")
    if isinstance(controlnet_cfg, dict):
        configured = controlnet_cfg.get("canny_path")
        if configured:
            return Path(configured)

    model_root = Path(os.getenv("MODEL_ROOT", "/models"))
    return model_root / "controlnet" / "sdxl_canny"


def _resolve_lora_path(payload: dict[str, Any]) -> Path | None:
    override = os.getenv("SDXL_LORA_PATH")
    if override:
        return Path(override)

    lora_cfg = payload.get("lora")
    if isinstance(lora_cfg, dict):
        configured = lora_cfg.get("path")
        if configured:
            return Path(configured)
    return None


def _resolve_lora_scale(payload: dict[str, Any]) -> float:
    override = os.getenv("LORA_SCALE")
    if override:
        try:
            return float(override)
        except ValueError:
            pass

    lora_cfg = payload.get("lora")
    if isinstance(lora_cfg, dict):
        configured = lora_cfg.get("scale")
        if configured is not None:
            try:
                return float(configured)
            except (TypeError, ValueError):
                pass
    return 1.0


def _resolve_prompts(payload: dict[str, Any]) -> tuple[str, str]:
    profile = payload.get("prompt_profile")
    if not isinstance(profile, dict):
        return ("Traditional Chinese gongbi painting", "low quality, watermark, text, logo")

    positive = str(profile.get("positive", "")).strip() or "Traditional Chinese gongbi painting"
    negative = str(profile.get("negative", "")).strip() or "low quality, watermark, text, logo"
    return positive, negative


def _ensure_model_exists(path: Path, name: str) -> Path:
    if path.exists():
        return path
    raise DiffusersBackendUnavailable(
        f"{name} not found at {path}. "
        "Please mount model weights to /models and check STYLE_CONFIG_PATH."
    )


def _prepare_pipeline(pipe, torch_module):
    device = _model_device()
    if device.startswith("cuda"):
        if not torch_module.cuda.is_available():
            raise DiffusersBackendUnavailable("MODEL_DEVICE is cuda but torch.cuda is unavailable")
        pipe.to("cuda")
    else:
        pipe.to(device)

    try:
        pipe.enable_attention_slicing()
    except Exception:
        pass
    try:
        pipe.enable_vae_tiling()
    except Exception:
        pass
    try:
        pipe.set_progress_bar_config(disable=True)
    except Exception:
        pass


def _load_lora(pipe, payload: dict[str, Any]) -> tuple[bool, float]:
    lora_path = _resolve_lora_path(payload)
    if not lora_path:
        return False, 1.0

    lora_scale = _resolve_lora_scale(payload)
    if not lora_path.exists():
        raise DiffusersBackendUnavailable(f"LoRA weight not found: {lora_path}")

    if lora_path.is_file():
        pipe.load_lora_weights(str(lora_path.parent), weight_name=lora_path.name)
    else:
        pipe.load_lora_weights(str(lora_path))

    try:
        pipe.fuse_lora(lora_scale=lora_scale)
        return True, lora_scale
    except Exception:
        return False, lora_scale


def _make_generator(torch_module, seed: int):
    device = "cuda" if _model_device().startswith("cuda") else "cpu"
    return torch_module.Generator(device=device).manual_seed(int(seed))


@lru_cache(maxsize=1)
def _style_runtime():
    _check_imports()
    import torch
    from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline

    payload = _style_payload()
    base_model_path = _ensure_model_exists(_resolve_base_model_path(payload), "SDXL base model")
    controlnet_path = _ensure_model_exists(_resolve_controlnet_path(payload), "ControlNet canny model")
    dtype = _torch_dtype(torch)

    controlnet = ControlNetModel.from_pretrained(
        str(controlnet_path),
        torch_dtype=dtype,
        local_files_only=True,
    )
    pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
        str(base_model_path),
        controlnet=controlnet,
        torch_dtype=dtype,
        local_files_only=True,
    )

    lora_fused, lora_scale = _load_lora(pipe, payload)
    _prepare_pipeline(pipe, torch)
    prompts = _resolve_prompts(payload)
    return pipe, lora_fused, lora_scale, prompts, torch


@lru_cache(maxsize=1)
def _inpaint_runtime():
    _check_imports()
    import torch
    from diffusers import StableDiffusionXLInpaintPipeline

    payload = _style_payload()
    inpaint_model_path = _ensure_model_exists(_resolve_inpaint_model_path(payload), "SDXL inpaint model")
    dtype = _torch_dtype(torch)

    pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
        str(inpaint_model_path),
        torch_dtype=dtype,
        local_files_only=True,
    )

    lora_fused, lora_scale = _load_lora(pipe, payload)
    _prepare_pipeline(pipe, torch)
    prompts = _resolve_prompts(payload)
    return pipe, lora_fused, lora_scale, prompts, torch


def _paste_rgba(canvas: Image.Image, layer: Any) -> None:
    layer_img = layer.image.convert("RGBA").resize((layer.bbox_w, layer.bbox_h), Image.Resampling.LANCZOS)
    canvas.alpha_composite(layer_img, (layer.bbox_x, layer.bbox_y))


def _build_boundary_band(height: int, width: int, masks: list[np.ndarray]) -> np.ndarray:
    full = np.zeros((height, width), dtype=np.uint8)
    for mask in masks:
        full = np.maximum(full, mask.astype(np.uint8))

    dilated = cv2.dilate(full, np.ones((32, 32), np.uint8), iterations=1)
    eroded = cv2.erode(full, np.ones((16, 16), np.uint8), iterations=1)
    band = cv2.subtract(dilated, eroded)
    return (band > 0).astype(np.uint8)


def _bbox_from_mask(mask: np.ndarray, pad: int = 64) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        return None

    h, w = mask.shape
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(w, int(xs.max()) + 1 + pad)
    y1 = min(h, int(ys.max()) + 1 + pad)
    return x0, y0, x1, y1


def style_crop_diffusers(
    crop_image: Image.Image,
    crop_mask,
    *,
    seed: int,
    controlnet_weight: float,
) -> Image.Image:
    pipe, lora_fused, lora_scale, prompts, torch_module = _style_runtime()
    positive_prompt, negative_prompt = prompts

    original_size = crop_image.size
    image_rgb = crop_image.convert("RGB")
    mask_np = (np.array(crop_mask).astype(np.uint8) > 0).astype(np.uint8)

    target_long = _env_int("SDXL_SIZE", 1024)
    model_input, _ = _resize_pair_for_model(
        image_rgb,
        None,
        target_long_side=target_long,
        min_short_side=512,
    )
    control_image = _build_canny_control(model_input)

    kwargs: dict[str, Any] = {
        "prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "image": model_input,
        "control_image": control_image,
        "num_inference_steps": _env_int("SDXL_STEPS", 28),
        "guidance_scale": _env_float("SDXL_CFG", 6.5),
        "strength": _env_float("STYLE_DENOISE", 0.55),
        "controlnet_conditioning_scale": float(np.clip(controlnet_weight, 0.0, 1.5)),
        "generator": _make_generator(torch_module, seed),
    }
    if not lora_fused:
        kwargs["cross_attention_kwargs"] = {"scale": lora_scale}

    result = pipe(**kwargs).images[0].convert("RGB")
    result = result.resize(original_size, Image.Resampling.LANCZOS)

    if mask_np.shape[0] != original_size[1] or mask_np.shape[1] != original_size[0]:
        mask_np = cv2.resize(mask_np, original_size, interpolation=cv2.INTER_NEAREST)
    alpha = (mask_np > 0).astype(np.uint8) * 255

    rgba = np.array(result.convert("RGBA"))
    rgba[..., 3] = alpha
    return Image.fromarray(rgba, mode="RGBA")


def seam_inpaint_diffusers(source: Image.Image, layers, *, seam_pass_count: int) -> Image.Image:
    pipe, lora_fused, lora_scale, prompts, torch_module = _inpaint_runtime()
    positive_prompt, negative_prompt = prompts
    prompt = (
        f"{positive_prompt}, seamless transition between painted regions, "
        "consistent brush lines, coherent colors"
    )

    base_rgba = source.convert("RGBA")
    width, height = base_rgba.size
    for layer in layers:
        _paste_rgba(base_rgba, layer)

    working = base_rgba.convert("RGB")
    masks = [decode_mask_rle(layer.mask_rle) for layer in layers]
    boundary = _build_boundary_band(height, width, masks)
    if int(boundary.max()) == 0:
        return working

    bbox = _bbox_from_mask(boundary, pad=64)
    if not bbox:
        return working

    x0, y0, x1, y1 = bbox
    boundary_patch = boundary[y0:y1, x0:x1].astype(np.uint8)
    if int(boundary_patch.max()) == 0:
        return working

    mask_image_full = Image.fromarray((boundary_patch * 255).astype(np.uint8), mode="L")

    for pass_idx in range(max(1, seam_pass_count)):
        patch = working.crop((x0, y0, x1, y1)).convert("RGB")
        run_patch, run_mask = _resize_pair_for_model(
            patch,
            mask_image_full,
            target_long_side=_env_int("SDXL_SIZE", 1024),
            min_short_side=512,
        )
        assert run_mask is not None

        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "image": run_patch,
            "mask_image": run_mask,
            "num_inference_steps": _env_int("INPAINT_STEPS", 24),
            "guidance_scale": _env_float("SDXL_CFG", 6.5),
            "strength": _env_float("INPAINT_DENOISE", 0.45),
            "generator": _make_generator(torch_module, _env_int("INPAINT_SEED_BASE", 20260306) + pass_idx),
        }
        if not lora_fused:
            kwargs["cross_attention_kwargs"] = {"scale": lora_scale}

        refined = pipe(**kwargs).images[0].convert("RGB")
        refined = refined.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)

        src_patch = np.array(patch, dtype=np.uint8)
        out_patch = np.array(refined, dtype=np.uint8)
        mask_np = np.array(mask_image_full.resize((x1 - x0, y1 - y0), Image.Resampling.NEAREST), dtype=np.uint8)
        blend_mask = (mask_np > 0)[:, :, None]
        merged_patch = np.where(blend_mask, out_patch, src_patch).astype(np.uint8)

        working.paste(Image.fromarray(merged_patch, mode="RGB"), (x0, y0))

    return working
