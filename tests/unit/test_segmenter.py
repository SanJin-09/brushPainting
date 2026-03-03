from PIL import Image

from model_runtime.segmenter import segment_image


def test_segmenter_deterministic_with_seed():
    image = Image.new("RGB", (640, 480), "white")

    first = segment_image(
        image,
        seed=2026,
        crop_count=6,
        min_area_ratio=0.02,
        max_area_ratio=0.35,
        max_overlap_iou=0.2,
    )
    second = segment_image(
        image,
        seed=2026,
        crop_count=6,
        min_area_ratio=0.02,
        max_area_ratio=0.35,
        max_overlap_iou=0.2,
    )

    assert len(first) == 6
    assert [x.__dict__ for x in first] == [x.__dict__ for x in second]
