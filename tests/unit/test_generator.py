import numpy as np
from PIL import Image

from model_runtime.generator import choose_bucket, generate_image, prepare_bucket, restore_from_bucket


def test_choose_bucket_by_orientation():
    assert choose_bucket((1600, 900)) == (1344, 768)
    assert choose_bucket((900, 1600)) == (768, 1344)
    assert choose_bucket((1000, 900)) == (1024, 1024)


def test_bucket_round_trip_preserves_size_without_stretching():
    source = Image.new("RGB", (1200, 500), "#cfa671")
    prepared, placement = prepare_bucket(source)
    restored = restore_from_bucket(prepared, placement, source.size)

    assert prepared.size == (1344, 768)
    assert restored.size == source.size
    assert np.array(restored).mean() > 0


def test_mock_generation_is_deterministic_and_supports_semantic_prompt(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "mock")
    source = Image.new("RGB", (96, 72), "#cfa671")

    first, first_params = generate_image(source, seed=12)
    second, _ = generate_image(source, seed=12)
    edited, edited_params = generate_image(source, seed=12, user_prompt="把衣服改成红色")

    assert np.array_equal(np.array(first), np.array(second))
    assert not np.array_equal(np.array(first), np.array(edited))
    assert first_params["bucket"] == [1344, 768]
    assert "把衣服改成红色" in edited_params["prompt"]
