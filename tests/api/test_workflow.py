from io import BytesIO
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

import services.api.app.api.routes as routes
from services.api.app.main import app
from services.api.app.services.storage import LocalStorage
from services.worker.tasks import run_generation


def _image_bytes(color: str = "#cfa671", size: tuple[int, int] = (96, 72), format: str = "PNG") -> bytes:
    image = Image.new("RGB", size, color)
    buffer = BytesIO()
    image.save(buffer, format=format)
    return buffer.getvalue()


def _sync_dispatch(job_id: str) -> None:
    run_generation(job_id)


def _upload(client: TestClient, count: int = 1) -> dict:
    files = [
        ("files", (f"source-{index}.png", _image_bytes(color=f"#{index + 3:02x}a671"), "image/png"))
        for index in range(count)
    ]
    response = client.post("/api/images/upload", files=files)
    assert response.status_code == 200
    return response.json()


def test_complete_batch_generate_regenerate_edit_export_flow(monkeypatch):
    monkeypatch.setattr(routes, "dispatch_job", _sync_dispatch)
    client = TestClient(app)
    upload = _upload(client, count=3)
    batch_id = upload["batch_id"]
    image_id = upload["images"][0]["id"]

    response = client.post(f"/api/batches/{batch_id}/generate")
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 3

    response = client.get(f"/api/batches/{batch_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert all(image["active_version_id"] for image in response.json()["images"])

    versions = client.get(f"/api/images/{image_id}/versions").json()
    initial_version_id = versions["active_version_id"]
    assert versions["versions"][0]["kind"] == "initial"

    response = client.post(f"/api/images/{image_id}/regenerate", json={"seed": 7})
    assert response.status_code == 200
    regenerate_job_id = response.json()["id"]
    assert client.get(f"/api/jobs/{regenerate_job_id}").json()["status"] == "succeeded"

    versions = client.get(f"/api/images/{image_id}/versions").json()
    regenerate_version_id = versions["active_version_id"]
    assert regenerate_version_id != initial_version_id
    assert versions["versions"][0]["kind"] == "regenerate"

    response = client.post(
        f"/api/images/{image_id}/edit",
        json={"version_id": initial_version_id, "user_prompt": "把衣服改成红色", "seed": 8},
    )
    assert response.status_code == 200
    edit_job_id = response.json()["id"]
    assert client.get(f"/api/jobs/{edit_job_id}").json()["status"] == "succeeded"

    versions = client.get(f"/api/images/{image_id}/versions").json()
    edited = versions["versions"][0]
    assert edited["kind"] == "semantic_edit"
    assert edited["parent_version_id"] == initial_version_id
    assert edited["user_prompt"] == "把衣服改成红色"
    assert versions["active_version_id"] == edited["id"]

    response = client.post(f"/api/batches/{batch_id}/export")
    assert response.status_code == 200
    zip_path = LocalStorage().url_to_path(response.json()["zip_url"])
    with zipfile.ZipFile(zip_path) as archive:
        assert len(archive.namelist()) == 3
        assert all(name.endswith(".png") for name in archive.namelist())


def test_generate_is_idempotent(monkeypatch):
    monkeypatch.setattr(routes, "dispatch_job", _sync_dispatch)
    client = TestClient(app)
    upload = _upload(client)
    batch_id = upload["batch_id"]

    first = client.post(f"/api/batches/{batch_id}/generate").json()["jobs"][0]["id"]
    second = client.post(f"/api/batches/{batch_id}/generate").json()["jobs"][0]["id"]

    assert second == first


def test_same_image_rejects_second_active_job(monkeypatch):
    monkeypatch.setattr(routes, "dispatch_job", lambda _job_id: None)
    client = TestClient(app)
    image_id = _upload(client)["images"][0]["id"]

    response = client.post(f"/api/images/{image_id}/regenerate")
    assert response.status_code == 200
    response = client.post(f"/api/images/{image_id}/regenerate")
    assert response.status_code == 409


def test_upload_validation_and_removed_session_routes():
    client = TestClient(app)
    invalid = client.post("/api/images/upload", files=[("files", ("bad.txt", b"not an image", "text/plain"))])
    assert invalid.status_code == 422

    too_many = [
        ("files", (f"{index}.png", _image_bytes(), "image/png"))
        for index in range(6)
    ]
    response = client.post("/api/images/upload", files=too_many)
    assert response.status_code == 422
    assert client.post("/api/v1/sessions").status_code == 404


def test_edit_requires_version_from_same_image(monkeypatch):
    monkeypatch.setattr(routes, "dispatch_job", _sync_dispatch)
    client = TestClient(app)
    upload = _upload(client, count=2)
    client.post(f"/api/batches/{upload['batch_id']}/generate")
    first, second = upload["images"]
    foreign_version = client.get(f"/api/images/{second['id']}/versions").json()["active_version_id"]

    response = client.post(
        f"/api/images/{first['id']}/edit",
        json={"version_id": foreign_version, "user_prompt": "修改颜色"},
    )
    assert response.status_code == 404


def test_edit_rejects_blank_prompt():
    client = TestClient(app)
    image_id = _upload(client)["images"][0]["id"]

    response = client.post(
        f"/api/images/{image_id}/edit",
        json={"version_id": "missing", "user_prompt": "   "},
    )
    assert response.status_code == 422


def test_media_route_does_not_expose_database_or_traversal():
    client = TestClient(app)

    assert client.get("/media/test.db").status_code == 404
    assert client.get("/media/../README.md").status_code == 404
