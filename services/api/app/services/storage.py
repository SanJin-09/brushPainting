from __future__ import annotations

import io
import re
import uuid
import zipfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from services.api.app.core.config import get_settings
from services.api.app.services.errors import ValidationError

ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
PUBLIC_MEDIA_SUFFIXES = {
    "uploads": {".png"},
    "outputs": {".png"},
    "thumbs": {".jpg", ".jpeg"},
    "exports": {".zip"},
}


class LocalStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.root = self.settings.runtime_root_path
        for name in ("uploads", "outputs", "thumbs", "exports"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def prepare_upload(self, raw: bytes) -> Image.Image:
        if not raw:
            raise ValidationError("上传文件为空")
        if len(raw) > self.settings.max_upload_bytes:
            raise ValidationError(f"单个文件不能超过 {self.settings.max_upload_bytes // (1024 * 1024)} MB")
        try:
            with Image.open(io.BytesIO(raw)) as opened:
                if (opened.format or "").upper() not in ALLOWED_FORMATS:
                    raise ValidationError("仅支持 PNG、JPEG 和 WebP 图片")
                opened.verify()
            with Image.open(io.BytesIO(raw)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        except ValidationError:
            raise
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValidationError("文件不是有效图片") from exc

        if max(image.size) > self.settings.max_image_edge:
            raise ValidationError(f"图片最大边不能超过 {self.settings.max_image_edge} 像素")
        return image

    def save_upload(self, batch_id: str, image_id: str, image: Image.Image) -> tuple[str, str]:
        original_path = self.root / "uploads" / batch_id / f"{image_id}.png"
        thumb_path = self.root / "thumbs" / batch_id / f"{image_id}.jpg"
        original_path.parent.mkdir(parents=True, exist_ok=True)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(original_path, format="PNG")
        thumbnail = image.copy()
        thumbnail.thumbnail((self.settings.thumbnail_max_edge, self.settings.thumbnail_max_edge), Image.Resampling.LANCZOS)
        thumbnail.save(thumb_path, format="JPEG", quality=85, optimize=True)
        return self.path_to_url(original_path), self.path_to_url(thumb_path)

    def save_output(self, image_id: str, version_id: str, image: Image.Image) -> str:
        path = self.root / "outputs" / image_id / f"{version_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(path, format="PNG")
        return self.path_to_url(path)

    def save_segment(
        self,
        image_id: str,
        segment_id: str,
        *,
        mask: Image.Image,
        crop: Image.Image,
    ) -> tuple[str, str]:
        directory = self.root / "outputs" / image_id / "segments"
        mask_path = directory / f"{segment_id}-mask.png"
        crop_path = directory / f"{segment_id}.png"
        directory.mkdir(parents=True, exist_ok=True)
        mask.convert("L").save(mask_path, format="PNG")
        crop.convert("RGBA").save(crop_path, format="PNG")
        return self.path_to_url(mask_path), self.path_to_url(crop_path)

    def remove_media(self, url: str | None) -> None:
        if not url:
            return
        try:
            path = self.url_to_path(url)
        except ValueError:
            return
        path.unlink(missing_ok=True)

    def create_export(self, batch_id: str, items: list[tuple[str, str, str]]) -> str:
        path = self.root / "exports" / f"{batch_id}-{uuid.uuid4().hex[:8]}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        used_names: set[str] = set()
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for image_id, original_filename, output_url in items:
                source_name = Path(original_filename.replace("\\", "/")).name
                stem = re.sub(r"[/\x00-\x1f]", "_", Path(source_name).stem).strip(" .") or image_id
                name = f"{stem}.png"
                if name in used_names:
                    name = f"{stem}-{image_id[:8]}.png"
                used_names.add(name)
                archive.write(self.url_to_path(output_url), arcname=name)
        return self.path_to_url(path)

    def path_to_url(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.root)
        return f"{self.settings.public_media_base.rstrip('/')}/{relative.as_posix()}"

    def url_to_path(self, url: str) -> Path:
        base = self.settings.public_media_base.rstrip("/")
        if not url.startswith(f"{base}/"):
            raise ValueError("不支持的媒体地址")
        path = (self.root / url[len(base) + 1 :]).resolve()
        if self.root not in path.parents:
            raise ValueError("媒体地址超出允许范围")
        return path

    def resolve_public_media(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if self.root not in path.parents:
            raise ValueError("媒体地址超出允许范围")
        relative = path.relative_to(self.root)
        if len(relative.parts) < 2:
            raise ValueError("媒体地址无效")
        allowed_suffixes = PUBLIC_MEDIA_SUFFIXES.get(relative.parts[0])
        if not allowed_suffixes or path.suffix.lower() not in allowed_suffixes:
            raise ValueError("媒体类型不允许")
        if not path.is_file():
            raise ValueError("媒体文件不存在")
        return path
