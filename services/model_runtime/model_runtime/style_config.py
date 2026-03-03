from __future__ import annotations

from pathlib import Path

import yaml


class StyleConfigError(RuntimeError):
    pass


def load_style_config(path: str) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        raise StyleConfigError(f"Style config not found: {path}")
    with file_path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f)
    if not isinstance(payload, dict) or "style_id" not in payload:
        raise StyleConfigError("Invalid style config")
    return payload
