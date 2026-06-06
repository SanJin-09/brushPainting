from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

INITIAL_PROMPT = (
    "将输入图像转换为中国传统工笔画风格。保持主体身份、原始构图、空间结构、数量关系和重要细节。"
    "使用细致墨线、雅致矿物色、层层晕染和传统绢本质感。"
)
SEMANTIC_PROMPT_TEMPLATE = (
    "请根据用户指令编辑输入图像，同时保持中国传统工笔画风格、主体身份、原始构图和未涉及内容的一致性。"
    "用户指令：{user_prompt}"
)


def choose_bucket(size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    ratio = width / height
    if ratio >= 1.2:
        return 1344, 768
    if ratio <= 1 / 1.2:
        return 768, 1344
    return 1024, 1024


def prepare_bucket(image: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]]:
    source = image.convert("RGB")
    target_w, target_h = choose_bucket(source.size)
    scale = min(target_w / source.width, target_h / source.height)
    resized_w = max(1, round(source.width * scale))
    resized_h = max(1, round(source.height * scale))
    resized = source.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
    left = (target_w - resized_w) // 2
    top = (target_h - resized_h) // 2
    right = target_w - resized_w - left
    bottom = target_h - resized_h - top
    array = np.asarray(resized)
    padded = np.pad(array, ((top, bottom), (left, right), (0, 0)), mode="edge")
    return Image.fromarray(padded.astype(np.uint8), mode="RGB"), (left, top, resized_w, resized_h)


def restore_from_bucket(image: Image.Image, placement: tuple[int, int, int, int], original_size: tuple[int, int]) -> Image.Image:
    left, top, width, height = placement
    cropped = image.convert("RGB").crop((left, top, left + width, top + height))
    return cropped.resize(original_size, Image.Resampling.LANCZOS)


def compose_prompt(user_prompt: str | None) -> str:
    if not user_prompt:
        return INITIAL_PROMPT
    return SEMANTIC_PROMPT_TEMPLATE.format(user_prompt=user_prompt.strip())


def _mock_generate(image: Image.Image, *, seed: int, user_prompt: str | None) -> Image.Image:
    rgb = image.convert("RGB")
    softened = rgb.filter(ImageFilter.SMOOTH_MORE)
    result = ImageEnhance.Color(softened).enhance(0.72)
    result = ImageEnhance.Contrast(result).enhance(1.08)
    digest = hashlib.sha256(f"{seed}:{user_prompt or ''}".encode("utf-8")).digest()
    overlay = Image.new("RGB", result.size, (120 + digest[0] % 50, 92 + digest[1] % 45, 56 + digest[2] % 35))
    strength = 0.08 if user_prompt else 0.04
    return Image.blend(result, overlay, strength)


def _require_path(path: str, label: str) -> str:
    resolved = Path(path)
    if not resolved.exists():
        raise RuntimeError(f"{label} 不存在: {resolved}")
    return str(resolved)


@lru_cache(maxsize=1)
def _diffsynth_runtime():
    import glob

    import torch
    from diffsynth.pipelines.qwen_image import ModelConfig, QwenImagePipeline

    edit_root = _require_path(os.environ["QWEN_EDIT_MODEL_PATH"], "Qwen-Image-Edit-2511 模型")
    components_root = _require_path(os.environ["QWEN_IMAGE_COMPONENTS_PATH"], "Qwen-Image 组件")
    processor_root = _require_path(os.environ["QWEN_EDIT_PROCESSOR_PATH"], "Qwen-Image-Edit processor")
    lora_path = _require_path(os.environ["GONGBI_LORA_PATH"], "工笔 LoRA")
    if not torch.cuda.is_available():
        raise RuntimeError("正式 DiffSynth 推理需要可用的 NVIDIA CUDA GPU")

    def files(pattern: str) -> list[str]:
        matched = sorted(glob.glob(pattern))
        if not matched:
            raise RuntimeError(f"模型文件不存在: {pattern}")
        return matched

    pipe = QwenImagePipeline.from_pretrained(
        torch_dtype=torch.bfloat16,
        device="cuda",
        model_configs=[
            ModelConfig(path=files(f"{edit_root}/transformer/diffusion_pytorch_model*.safetensors")),
            ModelConfig(path=files(f"{components_root}/text_encoder/model*.safetensors")),
            ModelConfig(path=files(f"{components_root}/vae/diffusion_pytorch_model.safetensors")),
        ],
        tokenizer_config=None,
        processor_config=ModelConfig(path=processor_root),
    )
    pipe.load_lora(pipe.dit, lora_path, alpha=float(os.getenv("GONGBI_LORA_SCALE", "1.0")))
    return pipe


def preload_runtime() -> None:
    backend = os.getenv("MODEL_BACKEND", "mock").strip().lower()
    if backend == "diffsynth_qwen":
        _diffsynth_runtime()
    elif backend != "mock":
        raise RuntimeError(f"不支持的 MODEL_BACKEND: {backend}")


def generate_image(source: Image.Image, *, seed: int, user_prompt: str | None = None) -> tuple[Image.Image, dict[str, object]]:
    original_size = source.size
    model_input, placement = prepare_bucket(source)
    prompt = compose_prompt(user_prompt)
    backend = os.getenv("MODEL_BACKEND", "mock").strip().lower()

    if backend == "mock":
        generated = _mock_generate(model_input, seed=seed, user_prompt=user_prompt)
    elif backend == "diffsynth_qwen":
        pipe = _diffsynth_runtime()
        generated = pipe(
            prompt,
            edit_image=[model_input],
            seed=seed,
            num_inference_steps=int(os.getenv("QWEN_IMAGE_STEPS", "40")),
            height=model_input.height,
            width=model_input.width,
            edit_image_auto_resize=False,
            zero_cond_t=True,
        )
    else:
        raise RuntimeError(f"不支持的 MODEL_BACKEND: {backend}")

    return restore_from_bucket(generated, placement, original_size), {
        "backend": backend,
        "seed": seed,
        "prompt": prompt,
        "bucket": [model_input.width, model_input.height],
        "lora_scale": float(os.getenv("GONGBI_LORA_SCALE", "1.0")),
        "steps": int(os.getenv("QWEN_IMAGE_STEPS", "40")),
    }
