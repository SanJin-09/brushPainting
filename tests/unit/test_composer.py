import numpy as np
from PIL import Image

from model_runtime.composer import Layer, compose_with_seam_refine
from model_runtime.rle import encode_mask_rle


def test_compose_output_shape():
    base = Image.new("RGB", (320, 240), "#f0e6d2")
    layer_img = Image.new("RGBA", (100, 80), (180, 120, 90, 255))

    mask = np.zeros((240, 320), dtype=np.uint8)
    mask[50:130, 40:140] = 1
    layer = Layer(
        image=layer_img,
        bbox_x=40,
        bbox_y=50,
        bbox_w=100,
        bbox_h=80,
        mask_rle=encode_mask_rle(mask),
    )

    out = compose_with_seam_refine(base, [layer], seam_pass_count=1)
    assert out.size == (320, 240)
