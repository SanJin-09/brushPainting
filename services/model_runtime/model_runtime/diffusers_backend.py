from __future__ import annotations

from functools import lru_cache

from PIL import Image


class DiffusersBackendUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _check_imports() -> None:
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401
    except Exception as exc:
        raise DiffusersBackendUnavailable(
            "Diffusers backend is enabled but required packages are missing. "
            "Install torch + diffusers + transformers + accelerate + safetensors."
        ) from exc


def style_crop_diffusers(
    crop_image: Image.Image,
    crop_mask,
    *,
    seed: int,
    controlnet_weight: float,
) -> Image.Image:
    _check_imports()
    raise NotImplementedError(
        "Diffusers style backend stub: load SDXL + ControlNet + LoRA here and return RGBA crop output."
    )


def seam_inpaint_diffusers(source: Image.Image, layers, *, seam_pass_count: int) -> Image.Image:
    _check_imports()
    raise NotImplementedError(
        "Diffusers inpaint backend stub: load SDXL Inpaint here and run boundary-band inpaint."
    )
