import sys
import types

import numpy as np
from PIL import Image

from model_runtime.stylizer import inpaint_region, style_image


def test_style_image_mock_is_deterministic():
    image = Image.new("RGB", (64, 48), "white")

    first = style_image(image, seed=2026, controlnet_weight=0.7)
    second = style_image(image, seed=2026, controlnet_weight=0.7)

    assert first.size == image.size
    assert np.array_equal(np.array(first), np.array(second))


def test_inpaint_region_only_changes_mask_band():
    source = Image.new("RGB", (64, 64), "white")
    current = Image.new("RGB", (64, 64), "#d8c3a2")
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[20:44, 20:44] = 1

    edited = inpaint_region(
        current,
        source,
        mask,
        bbox_x=20,
        bbox_y=20,
        bbox_w=24,
        bbox_h=24,
        seed=7,
        controlnet_weight=0.7,
        context_pad=0,
        mask_feather=0,
        prompt_override=None,
    )

    edited_np = np.array(edited)
    current_np = np.array(current)
    diff = np.any(edited_np != current_np, axis=2)

    assert diff[:20, :].sum() == 0
    assert diff[44:, :].sum() == 0
    assert diff[:, :20].sum() == 0
    assert diff[:, 44:].sum() == 0
    assert diff[20:44, 20:44].sum() > 0


def test_zimage_backend_routes_for_zimage_and_diffusers_alias(monkeypatch):
    calls: list[tuple[str, int, float]] = []
    fake_backend = types.ModuleType("model_runtime.zimage_backend")

    def fake_style_image(source_image: Image.Image, *, seed: int, controlnet_weight: float) -> Image.Image:
        calls.append(("style", seed, controlnet_weight))
        return source_image.copy()

    fake_backend.style_image_zimage = fake_style_image
    monkeypatch.setitem(sys.modules, "model_runtime.zimage_backend", fake_backend)

    image = Image.new("RGB", (32, 24), "white")

    monkeypatch.setenv("MODEL_BACKEND", "zimage")
    result = style_image(image, seed=11, controlnet_weight=0.4)
    assert result.size == image.size

    monkeypatch.setenv("MODEL_BACKEND", "diffusers")
    result = style_image(image, seed=12, controlnet_weight=0.9)
    assert result.size == image.size

    assert calls == [("style", 11, 0.4), ("style", 12, 0.9)]
