import sys
from types import ModuleType
from types import SimpleNamespace

import numpy as np
from PIL import Image

from model_runtime import sam_engine


def test_mock_segmentation_returns_mask_and_transparent_crop(monkeypatch):
    monkeypatch.setenv("SAM3_BACKEND", "mock")
    source = Image.new("RGB", (96, 72), "#cfa671")

    segments = sam_engine.segment_image(source, "flower")

    assert len(segments) == 3
    assert all(segment.mask.mode == "L" for segment in segments)
    assert all(segment.mask.size == source.size for segment in segments)
    assert all(segment.crop.mode == "RGBA" for segment in segments)
    assert all(segment.crop.getchannel("A").getbbox() is not None for segment in segments)


def test_sam3_segmentation_uses_processor_state_api(monkeypatch):
    class FakeProcessor:
        def set_image(self, image):
            assert image.mode == "RGB"
            return {"image": image}

        def set_text_prompt(self, *, prompt, state):
            assert prompt == "flower"
            assert "image" in state
            masks = np.zeros((2, 1, 24, 32), dtype=np.float32)
            masks[0, 0, 2:12, 3:15] = 1
            masks[1, 0, 8:22, 18:30] = 1
            return {"masks": masks, "scores": np.array([0.91, 0.82])}

    monkeypatch.setenv("SAM3_BACKEND", "sam3")
    monkeypatch.setenv("SEGMENT_MIN_AREA_RATIO", "0.01")
    monkeypatch.setenv("SEGMENT_MAX_RESULTS", "12")
    monkeypatch.setattr(sam_engine, "_sam3_runtime", lambda: FakeProcessor())

    segments = sam_engine.segment_image(Image.new("RGB", (32, 24), "white"), "flower")

    assert len(segments) == 2
    assert {segment.confidence for segment in segments} == {0.91, 0.82}
    high_confidence = next(segment for segment in segments if segment.confidence == 0.91)
    assert high_confidence.bbox == (3, 2, 12, 10)
    assert high_confidence.crop.mode == "RGBA"


def test_sam3_runtime_passes_checkpoint_and_threshold_by_keyword(monkeypatch, tmp_path):
    calls = {}

    class FakeModel:
        pass

    def build_sam3_image_model(**kwargs):
        calls["builder"] = kwargs
        return FakeModel()

    class FakeProcessor:
        def __init__(self, model, **kwargs):
            calls["processor"] = {"model": model, **kwargs}

    sam3_package = ModuleType("sam3")
    sam3_package.__path__ = []
    model_package = ModuleType("sam3.model")
    model_package.__path__ = []
    builder_module = ModuleType("sam3.model_builder")
    builder_module.build_sam3_image_model = build_sam3_image_model
    processor_module = ModuleType("sam3.model.sam3_image_processor")
    processor_module.Sam3Processor = FakeProcessor
    torch_module = ModuleType("torch")
    torch_module.cuda = SimpleNamespace(is_available=lambda: False)

    monkeypatch.setitem(sys.modules, "torch", torch_module)
    monkeypatch.setitem(sys.modules, "sam3", sam3_package)
    monkeypatch.setitem(sys.modules, "sam3.model", model_package)
    monkeypatch.setitem(sys.modules, "sam3.model_builder", builder_module)
    monkeypatch.setitem(sys.modules, "sam3.model.sam3_image_processor", processor_module)

    checkpoint = tmp_path / "sam3.pt"
    checkpoint.write_bytes(b"checkpoint")
    monkeypatch.setenv("SAM3_CHECKPOINT_PATH", str(checkpoint))
    monkeypatch.setenv("SAM3_DEVICE", "cpu")
    monkeypatch.setenv("SAM3_SCORE_THRESHOLD", "0.42")
    sam_engine._sam3_runtime.cache_clear()

    processor = sam_engine._sam3_runtime()

    assert isinstance(processor, FakeProcessor)
    assert calls["builder"] == {
        "checkpoint_path": str(checkpoint),
        "device": "cpu",
        "eval_mode": True,
        "load_from_HF": False,
    }
    assert calls["processor"]["device"] == "cpu"
    assert calls["processor"]["confidence_threshold"] == 0.42
    sam_engine._sam3_runtime.cache_clear()
