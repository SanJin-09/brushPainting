from pathlib import Path

from PIL import Image

from services.api.app.core.config import get_settings


class LocalMediaStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.root = self.settings.media_root_path
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        path = self.root / "sessions" / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_source(self, session_id: str, filename: str, raw: bytes) -> str:
        ext = Path(filename).suffix.lower() or ".png"
        path = self.session_dir(session_id) / f"source{ext}"
        path.write_bytes(raw)
        return self.path_to_url(path)

    def save_image(self, session_id: str, relative_name: str, image: Image.Image) -> str:
        path = self.session_dir(session_id) / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return self.path_to_url(path)

    def save_json(self, session_id: str, relative_name: str, content: str) -> str:
        path = self.session_dir(session_id) / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self.path_to_url(path)

    def path_to_url(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.root)
        return f"{self.settings.public_media_base.rstrip('/')}/{rel.as_posix()}"

    def url_to_path(self, url: str) -> Path:
        base = self.settings.public_media_base.rstrip("/")
        if not url.startswith(base):
            raise ValueError(f"Unsupported media URL: {url}")
        rel = url[len(base) + 1 :]
        return self.root / rel
