from io import BytesIO
import sys
import types

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from model_runtime.rle import encode_mask_rle
from services.api.app.main import app
from services.worker.tasks import edit_mask, render_full
import services.api.app.api.routes as routes


def _image_bytes(color: str = "#cfa671") -> bytes:
    image = Image.new("RGB", (96, 72), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _sync_dispatch(task_name: str, *args):
    if task_name == "services.worker.tasks.render_full":
        render_full.run(*args)
        return
    if task_name == "services.worker.tasks.edit_mask":
        edit_mask.run(*args)
        return
    raise AssertionError(f"Unexpected task: {task_name}")


def _install_fake_qwen_backend(monkeypatch):
    fake_backend = types.ModuleType("model_runtime.qwen_image_backend")

    def fake_style_image(
        source_image: Image.Image,
        *,
        seed: int,
        controlnet_weight: float,
        progress_callback=None,
    ) -> Image.Image:
        _ = controlnet_weight
        if progress_callback is not None:
            progress_callback(1, 2, "正在准备 Qwen 模型")
            progress_callback(2, 2, "正在使用 Qwen 生成整图")
        return source_image.copy()

    def fake_resolve_qwen_runtime_config(payload=None):
        _ = payload
        return {
            "model_path": "/models/qwen_image_edit_2511",
            "prompt": "请保留原图细节并转成工笔画",
            "negative_prompt": " ",
            "steps": 40,
            "true_cfg_scale": 4.0,
            "guidance_scale": 1.0,
        }

    fake_backend.style_image_qwen = fake_style_image
    fake_backend.resolve_qwen_runtime_config = fake_resolve_qwen_runtime_config
    monkeypatch.setitem(sys.modules, "model_runtime.qwen_image_backend", fake_backend)


def test_full_render_edit_adopt_export_flow(monkeypatch):
    monkeypatch.setattr(routes, "dispatch_job", _sync_dispatch)
    client = TestClient(app)

    response = client.post(
        "/api/v1/sessions",
        files={"file": ("source.png", _image_bytes(), "image/png")},
    )
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    response = client.post(f"/api/v1/sessions/{session_id}/style/lock", json={"style_id": "gongbi_default"})
    assert response.status_code == 200

    response = client.post(f"/api/v1/sessions/{session_id}/render", json={})
    assert response.status_code == 200
    job_id = response.json()["id"]

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED"
    assert response.json()["progress_percent"] == 100
    assert response.json()["progress_message"] == "整图生成完成"

    response = client.get(f"/api/v1/sessions/{session_id}")
    assert response.status_code == 200
    session_payload = response.json()
    assert session_payload["supports_local_edit"] is True
    assert session_payload["local_edit_disabled_reason"] is None
    assert session_payload["current_version_id"] is not None
    assert len(session_payload["versions"]) == 1

    mask = np.zeros((72, 96), dtype=np.uint8)
    mask[18:54, 30:66] = 1
    response = client.post(
        f"/api/v1/sessions/{session_id}/mask-assist",
        json={"mask_rle": encode_mask_rle(mask)},
    )
    assert response.status_code == 200
    assist_payload = response.json()
    assert assist_payload["bbox_w"] > 0
    assert assist_payload["bbox_h"] > 0

    response = client.post(
        f"/api/v1/sessions/{session_id}/edits",
        json={
            "mask_rle": assist_payload["mask_rle"],
            "bbox_x": assist_payload["bbox_x"],
            "bbox_y": assist_payload["bbox_y"],
            "bbox_w": assist_payload["bbox_w"],
            "bbox_h": assist_payload["bbox_h"],
            "prompt_override": "花瓣更淡"
        },
    )
    assert response.status_code == 200
    edit_job_id = response.json()["id"]

    response = client.get(f"/api/v1/jobs/{edit_job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED"
    assert response.json()["progress_percent"] == 100
    assert response.json()["progress_message"] == "局部候选生成完成"

    response = client.get(f"/api/v1/sessions/{session_id}")
    assert response.status_code == 200
    session_payload = response.json()
    assert len(session_payload["versions"]) == 2
    candidate = next(version for version in session_payload["versions"] if not version["is_current"])

    response = client.post(f"/api/v1/sessions/{session_id}/versions/{candidate['id']}/adopt", json={})
    assert response.status_code == 200
    assert response.json()["current_version_id"] == candidate["id"]

    response = client.post(f"/api/v1/sessions/{session_id}/export", json={})
    assert response.status_code == 200
    export_payload = response.json()
    assert export_payload["final_image_url"]
    assert export_payload["manifest_url"]


def test_second_full_render_does_not_replace_current(monkeypatch):
    monkeypatch.setattr(routes, "dispatch_job", _sync_dispatch)
    client = TestClient(app)

    response = client.post(
        "/api/v1/sessions",
        files={"file": ("source.png", _image_bytes("#d8c3a2"), "image/png")},
    )
    session_id = response.json()["session_id"]
    client.post(f"/api/v1/sessions/{session_id}/style/lock", json={"style_id": "gongbi_default"})
    client.post(f"/api/v1/sessions/{session_id}/render", json={"seed": 3})

    first = client.get(f"/api/v1/sessions/{session_id}").json()["current_version_id"]
    client.post(f"/api/v1/sessions/{session_id}/render", json={"seed": 4})
    session_payload = client.get(f"/api/v1/sessions/{session_id}").json()

    assert session_payload["supports_local_edit"] is True
    assert session_payload["current_version_id"] == first
    assert len(session_payload["versions"]) == 2


def test_qwen_backend_render_disables_local_edit(monkeypatch):
    monkeypatch.setattr(routes, "dispatch_job", _sync_dispatch)
    monkeypatch.setenv("MODEL_BACKEND", "qwen_image")
    _install_fake_qwen_backend(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/v1/sessions",
        files={"file": ("source.png", _image_bytes("#c7b39a"), "image/png")},
    )
    assert response.status_code == 200
    session_id = response.json()["session_id"]

    response = client.post(f"/api/v1/sessions/{session_id}/style/lock", json={"style_id": "gongbi_default"})
    assert response.status_code == 200

    response = client.post(f"/api/v1/sessions/{session_id}/render", json={"seed": 12})
    assert response.status_code == 200
    job_id = response.json()["id"]

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED"

    response = client.get(f"/api/v1/sessions/{session_id}")
    assert response.status_code == 200
    session_payload = response.json()
    assert session_payload["supports_local_edit"] is False
    assert session_payload["local_edit_disabled_reason"] == "当前 Qwen 后端仅支持整图重绘"
    assert len(session_payload["versions"]) == 1

    response = client.post(
        f"/api/v1/sessions/{session_id}/mask-assist",
        json={"mask_rle": "placeholder"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "当前 Qwen 后端仅支持整图重绘"

    response = client.post(
        f"/api/v1/sessions/{session_id}/edits",
        json={
            "mask_rle": "placeholder",
            "bbox_x": 0,
            "bbox_y": 0,
            "bbox_w": 1,
            "bbox_h": 1,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "当前 Qwen 后端仅支持整图重绘"
