import sys
import types

import numpy as np
from PIL import Image
import pytest

from model_runtime.stylizer import inpaint_region, style_image


def test_style_image_mock_is_deterministic(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "mock")
    image = Image.new("RGB", (64, 48), "white")

    first = style_image(image, seed=2026, controlnet_weight=0.7)
    second = style_image(image, seed=2026, controlnet_weight=0.7)

    assert first.size == image.size
    assert np.array_equal(np.array(first), np.array(second))


def test_inpaint_region_only_changes_mask_band(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "mock")
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


def test_style_image_routes_to_zimage_backend(monkeypatch):
    calls: list[tuple[int, float]] = []
    fake_backend = types.ModuleType("model_runtime.zimage_backend")

    def fake_style_image(
        source_image: Image.Image,
        *,
        seed: int,
        controlnet_weight: float,
        progress_callback=None,
    ) -> Image.Image:
        _ = progress_callback
        calls.append((seed, controlnet_weight))
        return source_image.copy()

    fake_backend.style_image_zimage = fake_style_image
    monkeypatch.setitem(sys.modules, "model_runtime.zimage_backend", fake_backend)
    monkeypatch.setenv("MODEL_BACKEND", "zimage")

    image = Image.new("RGB", (32, 24), "white")
    result = style_image(image, seed=11, controlnet_weight=1.0)

    assert result.size == image.size
    assert calls == [(11, 1.0)]


def test_style_image_routes_to_qwen_backend(monkeypatch):
    calls: list[tuple[int, float]] = []
    fake_backend = types.ModuleType("model_runtime.qwen_image_backend")

    def fake_style_image(
        source_image: Image.Image,
        *,
        seed: int,
        controlnet_weight: float,
        progress_callback=None,
    ) -> Image.Image:
        _ = progress_callback
        calls.append((seed, controlnet_weight))
        return source_image.copy()

    fake_backend.style_image_qwen = fake_style_image
    monkeypatch.setitem(sys.modules, "model_runtime.qwen_image_backend", fake_backend)
    monkeypatch.setenv("MODEL_BACKEND", "qwen_image")

    image = Image.new("RGB", (32, 24), "white")
    result = style_image(image, seed=17, controlnet_weight=1.0)

    assert result.size == image.size
    assert calls == [(17, 1.0)]


def test_inpaint_region_rejects_qwen_backend(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "qwen_image")
    source = Image.new("RGB", (32, 32), "white")
    current = Image.new("RGB", (32, 32), "black")
    mask = np.zeros((32, 32), dtype=np.uint8)

    with pytest.raises(RuntimeError, match="Qwen backend does not support local masked edit"):
        inpaint_region(
            current,
            source,
            mask,
            bbox_x=0,
            bbox_y=0,
            bbox_w=8,
            bbox_h=8,
            seed=1,
            controlnet_weight=1.0,
            context_pad=0,
            mask_feather=0,
        )
