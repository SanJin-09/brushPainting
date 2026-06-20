import sys
from types import ModuleType

import pytest

from model_runtime.modelscope_loader import download_sam3_snapshot


def test_download_sam3_snapshot_filters_to_checkpoint(monkeypatch, tmp_path):
    calls = {}
    modelscope_module = ModuleType("modelscope")

    def snapshot_download(**kwargs):
        calls.update(kwargs)
        checkpoint = tmp_path / "sam3.pt"
        checkpoint.write_bytes(b"checkpoint")
        return str(tmp_path)

    modelscope_module.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "modelscope", modelscope_module)

    checkpoint = download_sam3_snapshot(
        model_id="facebook/sam3",
        revision="master",
        local_dir=tmp_path,
    )

    assert checkpoint == tmp_path / "sam3.pt"
    assert calls == {
        "model_id": "facebook/sam3",
        "revision": "master",
        "local_dir": str(tmp_path.resolve()),
        "allow_file_pattern": ["sam3.pt"],
    }


def test_download_sam3_snapshot_can_download_full_repo(monkeypatch, tmp_path):
    calls = {}
    modelscope_module = ModuleType("modelscope")

    def snapshot_download(**kwargs):
        calls.update(kwargs)
        checkpoint = tmp_path / "sam3.pt"
        checkpoint.write_bytes(b"checkpoint")
        return str(tmp_path)

    modelscope_module.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "modelscope", modelscope_module)

    download_sam3_snapshot(
        model_id="facebook/sam3",
        revision="master",
        local_dir=tmp_path,
        full_snapshot=True,
    )

    assert "allow_file_pattern" not in calls


def test_download_sam3_snapshot_rejects_parent_traversal(tmp_path):
    with pytest.raises(RuntimeError, match="相对路径"):
        download_sam3_snapshot(
            model_id="facebook/sam3",
            revision="master",
            local_dir=tmp_path,
            checkpoint_filename="../sam3.pt",
        )
