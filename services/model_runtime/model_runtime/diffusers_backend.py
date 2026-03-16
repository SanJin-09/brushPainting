from __future__ import annotations

"""Compatibility shim for the deprecated diffusers backend entrypoints."""

from model_runtime.zimage_backend import (
    ZImageBackendUnavailable as DiffusersBackendUnavailable,
    inpaint_region_zimage as inpaint_region_diffusers,
    style_image_zimage as style_image_diffusers,
)

__all__ = [
    "DiffusersBackendUnavailable",
    "style_image_diffusers",
    "inpaint_region_diffusers",
]
