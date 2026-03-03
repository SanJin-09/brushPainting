import numpy as np

from model_runtime.rle import decode_mask_rle, encode_mask_rle


def test_rle_roundtrip():
    mask = np.zeros((32, 48), dtype=np.uint8)
    mask[5:22, 7:31] = 1

    payload = encode_mask_rle(mask)
    restored = decode_mask_rle(payload)

    assert restored.shape == mask.shape
    assert np.array_equal(restored, mask)
