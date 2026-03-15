from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from services.api.app.core.config import get_settings
from services.api.app.services.errors import ConflictError, NotFoundError, ValidationError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
KEEP_DIR_NAME = "_manual_keep"
DISCARD_DIR_NAME = "_manual_discard"
STATE_FILE_NAME = "_manual_review_state.json"
SPECIAL_DIRS = {
    KEEP_DIR_NAME,
    DISCARD_DIR_NAME,
    "_offline_filter_reports",
    "_manual_filter_reports",
}
KEEP_HOTKEY = "K"
DISCARD_HOTKEY = "D"
UNDO_HOTKEY = "Z"


def get_review_state(directory: str) -> dict[str, Any]:
    review_dir, normalized_directory = _resolve_review_dir(directory)
    return _build_review_state(review_dir, normalized_directory)


def apply_review_action(directory: str, relative_path: str, action: Literal["keep", "discard"]) -> dict[str, Any]:
    review_dir, normalized_directory = _resolve_review_dir(directory)
    pending = _list_pending_images(review_dir)
    if not pending:
        raise ConflictError("当前目录没有待审核图片")

    current_relative_path = pending[0]
    normalized_relative_path = _normalize_relative_path(relative_path)
    if normalized_relative_path != current_relative_path:
        raise ConflictError("当前图片已变化，请刷新后重试")

    source_path = review_dir / Path(normalized_relative_path)
    if not source_path.exists():
        raise NotFoundError("待审核图片不存在")

    target_root = review_dir / (KEEP_DIR_NAME if action == "keep" else DISCARD_DIR_NAME)
    target_path = _next_available_target(target_root, Path(normalized_relative_path))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(target_path))

    state = _load_state(review_dir)
    history = state.setdefault("history", [])
    history.append(
        {
            "action": action,
            "source_relative_path": normalized_relative_path,
            "target_relative_path": target_path.relative_to(review_dir).as_posix(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_state(review_dir, state)
    return _build_review_state(review_dir, normalized_directory)


def undo_review_action(directory: str) -> dict[str, Any]:
    review_dir, normalized_directory = _resolve_review_dir(directory)
    state = _load_state(review_dir)
    history = state.setdefault("history", [])
    if not history:
        raise ConflictError("当前没有可撤销的操作")

    last = history.pop()
    target_relative = _normalize_relative_path(str(last.get("target_relative_path", "")))
    source_relative = _normalize_relative_path(str(last.get("source_relative_path", "")))
    if not target_relative or not source_relative:
        raise ConflictError("撤销记录损坏")

    target_path = review_dir / Path(target_relative)
    source_path = review_dir / Path(source_relative)
    if not target_path.exists():
        raise ConflictError("撤销目标不存在，无法恢复")
    if source_path.exists():
        raise ConflictError("原始位置已存在同名文件，无法撤销")

    source_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target_path), str(source_path))
    _save_state(review_dir, state)
    return _build_review_state(review_dir, normalized_directory)


def resolve_review_image_path(directory: str, relative_path: str) -> Path:
    review_dir, _ = _resolve_review_dir(directory)
    normalized_relative_path = _normalize_relative_path(relative_path)
    image_path = (review_dir / Path(normalized_relative_path)).resolve()
    if review_dir not in image_path.parents and image_path != review_dir:
        raise ValidationError("图片路径超出允许范围")
    if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValidationError("不支持的图片格式")
    if not image_path.is_file():
        raise NotFoundError("图片不存在")
    return image_path


def _build_review_state(review_dir: Path, normalized_directory: str) -> dict[str, Any]:
    pending = _list_pending_images(review_dir)
    keep = _list_bucket_images(review_dir / KEEP_DIR_NAME)
    discard = _list_bucket_images(review_dir / DISCARD_DIR_NAME)
    state = _load_state(review_dir)
    history = state.setdefault("history", [])
    current = None
    if pending:
        current = {
            "file_name": Path(pending[0]).name,
            "relative_path": pending[0],
        }
    return {
        "directory": normalized_directory,
        "current": current,
        "pending_count": len(pending),
        "keep_count": len(keep),
        "discard_count": len(discard),
        "reviewed_count": len(keep) + len(discard),
        "total_count": len(pending) + len(keep) + len(discard),
        "history_count": len(history),
        "keep_hotkey": KEEP_HOTKEY,
        "discard_hotkey": DISCARD_HOTKEY,
        "undo_hotkey": UNDO_HOTKEY,
    }


def _resolve_review_dir(directory: str) -> tuple[Path, str]:
    normalized_directory = _normalize_relative_path(directory)
    if not normalized_directory:
        raise ValidationError("目录不能为空")

    root = get_settings().reference_scrape_root_path
    review_dir = (root / Path(normalized_directory)).resolve()
    if root not in review_dir.parents and review_dir != root:
        raise ValidationError("目录超出允许范围")
    if not review_dir.exists() or not review_dir.is_dir():
        raise NotFoundError("审核目录不存在")
    return review_dir, normalized_directory


def _normalize_relative_path(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    while "//" in raw:
        raw = raw.replace("//", "/")
    raw = raw.strip("/")
    if not raw or raw in {".", ".."}:
        return raw
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise ValidationError("不允许的相对路径")
    return "/".join(parts)


def _list_pending_images(review_dir: Path) -> list[str]:
    items: list[str] = []
    for path in review_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        relative = path.relative_to(review_dir)
        if any(part in SPECIAL_DIRS for part in relative.parts[:-1]):
            continue
        items.append(relative.as_posix())
    items.sort()
    return items


def _list_bucket_images(bucket_dir: Path) -> list[str]:
    if not bucket_dir.is_dir():
        return []
    items = [path.relative_to(bucket_dir).as_posix() for path in bucket_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
    items.sort()
    return items


def _next_available_target(target_root: Path, relative_path: Path) -> Path:
    target = target_root / relative_path
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    counter = 2
    while True:
        candidate = target.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _load_state(review_dir: Path) -> dict[str, Any]:
    path = review_dir / STATE_FILE_NAME
    if not path.exists():
        return {"history": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConflictError("审核状态文件损坏") from exc


def _save_state(review_dir: Path, state: dict[str, Any]) -> None:
    path = review_dir / STATE_FILE_NAME
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
