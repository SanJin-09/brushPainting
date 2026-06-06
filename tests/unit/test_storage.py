from io import BytesIO
import zipfile

from PIL import Image

from services.api.app.services.errors import ValidationError
from services.api.app.services.storage import LocalStorage


def test_export_filename_cannot_create_nested_zip_path():
    storage = LocalStorage()
    output_url = storage.save_output("image", "version", Image.new("RGB", (10, 10), "white"))

    zip_url = storage.create_export("batch", [("image", "../unsafe.png", output_url)])

    with zipfile.ZipFile(storage.url_to_path(zip_url)) as archive:
        assert archive.namelist() == ["unsafe.png"]


def test_upload_applies_exif_orientation():
    storage = LocalStorage()
    source = Image.new("RGB", (12, 8), "white")
    exif = source.getexif()
    exif[274] = 6
    buffer = BytesIO()
    source.save(buffer, format="JPEG", exif=exif)

    prepared = storage.prepare_upload(buffer.getvalue())

    assert prepared.size == (8, 12)


def test_upload_rejects_image_over_max_edge(monkeypatch):
    storage = LocalStorage()
    monkeypatch.setattr(storage.settings, "max_image_edge", 8)
    buffer = BytesIO()
    Image.new("RGB", (9, 8), "white").save(buffer, format="WEBP")

    try:
        storage.prepare_upload(buffer.getvalue())
    except ValidationError as exc:
        assert "最大边" in str(exc)
    else:
        raise AssertionError("超出最大边长的图片应被拒绝")
