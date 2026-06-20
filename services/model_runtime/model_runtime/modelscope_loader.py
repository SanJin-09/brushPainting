from __future__ import annotations

from pathlib import Path


def download_sam3_snapshot(
    *,
    model_id: str,
    revision: str,
    local_dir: str | Path,
    checkpoint_filename: str = "sam3.pt",
    full_snapshot: bool = False,
) -> Path:
    """Download SAM 3 from ModelScope and return the local checkpoint path."""
    checkpoint_relative = Path(checkpoint_filename)
    if checkpoint_relative.is_absolute() or ".." in checkpoint_relative.parts:
        raise RuntimeError(
            f"SAM 3 checkpoint 文件名必须是模型仓库内的相对路径: {checkpoint_filename}"
        )

    try:
        from modelscope import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "使用 ModelScope 下载 SAM 3 需要安装 modelscope: pip install modelscope"
        ) from exc

    destination = Path(local_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    download_options: dict[str, object] = {
        "model_id": model_id,
        "revision": revision,
        "local_dir": str(destination),
    }
    if not full_snapshot:
        download_options["allow_file_pattern"] = [checkpoint_filename]

    model_dir = Path(snapshot_download(**download_options))
    checkpoint = model_dir / checkpoint_relative
    if not checkpoint.is_file():
        raise RuntimeError(
            f"ModelScope 模型 {model_id}@{revision} 下载完成，但未找到权重: {checkpoint}"
        )
    return checkpoint
