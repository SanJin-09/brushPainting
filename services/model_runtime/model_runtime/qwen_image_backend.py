from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
import inspect
import os
from pathlib import Path
from typing import Any

from PIL import Image

from model_runtime.style_config import StyleConfigError, load_style_config


class QwenImageBackendUnavailable(RuntimeError):
    pass


ProgressCallback = Callable[[int, int, str], None]

BASE_QWEN_EDIT_PROMPT = (
    "请将输入图像以中国传统工笔画风格进行重绘，保留原始构图、主体身份、数量关系、姿态、服饰纹样、配饰、"
    "背景元素和所有可见细节，不要新增、删除、替换或重排任何关键内容。"
)


@lru_cache(maxsize=1)
def _check_imports() -> None:
    try:
        import diffusers  # noqa: F401
        import safetensors  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception as exc:
        raise QwenImageBackendUnavailable(
            "Qwen image backend is enabled but required packages are missing. "
            "Install torch + diffusers + transformers + safetensors."
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


@lru_cache(maxsize=1)
def _style_payload() -> dict[str, Any]:
    style_config_path = os.getenv("STYLE_CONFIG_PATH", "/app/configs/styles/gongbi_default.yaml")
    try:
        return load_style_config(style_config_path)
    except StyleConfigError as exc:
        raise QwenImageBackendUnavailable(str(exc)) from exc


def _payload_render_value(payload: dict[str, Any], key: str) -> Any | None:
    render = payload.get("render")
    if not isinstance(render, dict):
        return None
    return render.get(key)


def _resolve_model_path(payload: dict[str, Any]) -> Path:
    override = os.getenv("QWEN_IMAGE_MODEL_PATH")
    if override:
        return Path(override)

    models = payload.get("models")
    if isinstance(models, dict):
        configured = models.get("qwen_image_model_path")
        if configured:
            return Path(configured)

    model_root = Path(os.getenv("MODEL_ROOT", "/models"))
    return model_root / "qwen_image_edit_2511"


def _resolve_positive_prompt(payload: dict[str, Any]) -> str:
    profile = payload.get("prompt_profile")
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("positive", "")).strip()


def _resolve_negative_prompt(payload: dict[str, Any]) -> str:
    profile = payload.get("prompt_profile")
    if not isinstance(profile, dict):
        return " "
    negative = str(profile.get("negative", "")).strip()
    return negative or " "


def _resolve_steps(payload: dict[str, Any]) -> int:
    configured = _payload_render_value(payload, "qwen_image_steps")
    if configured is not None:
        try:
            return int(configured)
        except (TypeError, ValueError):
            pass
    return _env_int("QWEN_IMAGE_STEPS", 40)


def _resolve_true_cfg_scale(payload: dict[str, Any]) -> float:
    configured = _payload_render_value(payload, "qwen_image_true_cfg_scale")
    if configured is not None:
        try:
            return float(configured)
        except (TypeError, ValueError):
            pass
    return _env_float("QWEN_IMAGE_TRUE_CFG_SCALE", 4.0)


def _resolve_guidance_scale(payload: dict[str, Any]) -> float:
    configured = _payload_render_value(payload, "qwen_image_guidance_scale")
    if configured is not None:
        try:
            return float(configured)
        except (TypeError, ValueError):
            pass
    return _env_float("QWEN_IMAGE_GUIDANCE_SCALE", 1.0)


def compose_qwen_edit_prompt(style_positive: str) -> str:
    if not style_positive.strip():
        return BASE_QWEN_EDIT_PROMPT
    return f"{BASE_QWEN_EDIT_PROMPT} {style_positive.strip()}"


def resolve_qwen_runtime_config(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_payload = payload or _style_payload()
    return {
        "model_path": str(_resolve_model_path(resolved_payload)),
        "prompt": compose_qwen_edit_prompt(_resolve_positive_prompt(resolved_payload)),
        "negative_prompt": _resolve_negative_prompt(resolved_payload),
        "steps": _resolve_steps(resolved_payload),
        "true_cfg_scale": _resolve_true_cfg_scale(resolved_payload),
        "guidance_scale": _resolve_guidance_scale(resolved_payload),
    }


def _ensure_model_exists(path: Path) -> Path:
    if path.exists():
        return path
    raise QwenImageBackendUnavailable(
        f"Qwen image model not found at {path}. "
        "Please mount Qwen/Qwen-Image-Edit-2511 weights and check QWEN_IMAGE_MODEL_PATH."
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


def _prepare_pipeline(pipe, torch_module) -> None:
    device = _model_device()
    if device.startswith("cuda"):
        if not torch_module.cuda.is_available():
            raise QwenImageBackendUnavailable("MODEL_DEVICE is cuda but torch.cuda is unavailable")
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


def _attach_progress_callback(
    pipe,
    kwargs: dict[str, Any],
    *,
    progress_callback: ProgressCallback | None,
    message: str,
) -> tuple[dict[str, Any], int]:
    total_steps = int(kwargs.get("num_inference_steps", 0) or 0)
    if progress_callback is None or total_steps <= 0:
        return kwargs, total_steps
    try:
        parameters = inspect.signature(pipe.__call__).parameters
    except (TypeError, ValueError):
        return kwargs, total_steps
    if "callback_on_step_end" not in parameters:
        return kwargs, total_steps

    def _on_step_end(_pipe, step_index, _timestep, callback_kwargs):
        progress_callback(min(step_index + 1, total_steps), total_steps, message)
        return callback_kwargs

    kwargs["callback_on_step_end"] = _on_step_end
    if "callback_on_step_end_tensor_inputs" in parameters:
        kwargs["callback_on_step_end_tensor_inputs"] = []
    return kwargs, total_steps


@lru_cache(maxsize=1)
def _runtime():
    _check_imports()
    import torch
    from diffusers import QwenImageEditPlusPipeline

    payload = _style_payload()
    model_path = _ensure_model_exists(_resolve_model_path(payload))
    dtype = _torch_dtype(torch)
    pipe = QwenImageEditPlusPipeline.from_pretrained(
        str(model_path),
        **_pretrained_kwargs(model_path, torch_dtype=dtype),
    )
    _prepare_pipeline(pipe, torch)
    return pipe, torch, payload


def style_image_qwen(
    source_image: Image.Image,
    *,
    seed: int,
    controlnet_weight: float,
    progress_callback: ProgressCallback | None = None,
) -> Image.Image:
    _ = controlnet_weight
    if progress_callback is not None:
        progress_callback(1, 3, "正在准备 Qwen 模型")
    pipe, torch_module, payload = _runtime()
    runtime_config = resolve_qwen_runtime_config(payload)
    if progress_callback is not None:
        progress_callback(2, 3, "正在使用 Qwen 生成整图")

    original_size = source_image.size
    image_rgb = source_image.convert("RGB")

    kwargs: dict[str, Any] = {
        "image": [image_rgb],
        "prompt": runtime_config["prompt"],
        "negative_prompt": runtime_config["negative_prompt"],
        "generator": _make_generator(torch_module, seed),
        "true_cfg_scale": runtime_config["true_cfg_scale"],
        "guidance_scale": runtime_config["guidance_scale"],
        "num_inference_steps": runtime_config["steps"],
        "num_images_per_prompt": 1,
    }
    kwargs, _total_steps = _attach_progress_callback(
        pipe,
        kwargs,
        progress_callback=progress_callback,
        message="正在使用 Qwen 生成整图",
    )

    result = pipe(**kwargs).images[0].convert("RGB")
    if progress_callback is not None:
        progress_callback(3, 3, "正在整理 Qwen 输出")
    if result.size != original_size:
        return result.resize(original_size, Image.Resampling.LANCZOS)
    return result
