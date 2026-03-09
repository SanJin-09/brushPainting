import numpy as np
from PIL import Image

from model_runtime.mask_assist import refine_mask
from model_runtime.rle import decode_mask_rle


def test_mask_assist_mock_returns_valid_bbox_and_mask():
    image = Image.new("RGB", (80, 60), "white")
    mask = np.zeros((60, 80), dtype=np.uint8)
    mask[10:30, 15:45] = 1

    result = refine_mask(image, mask)
    restored = decode_mask_rle(result.mask_rle)

    assert restored.shape == mask.shape
    assert restored.sum() > 0
    assert result.bbox_x >= 0
    assert result.bbox_y >= 0
    assert result.bbox_w > 0
    assert result.bbox_h > 0
