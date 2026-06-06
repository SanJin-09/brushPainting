#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8000/api}"
export API_BASE

python3 - <<'PY'
import io
import os
import time
import zipfile

import httpx
from PIL import Image

api = os.environ["API_BASE"].rstrip("/")
client = httpx.Client(timeout=30)


def image_bytes(color):
    buffer = io.BytesIO()
    Image.new("RGB", (96, 72), color).save(buffer, format="PNG")
    return buffer.getvalue()


def poll(job_id):
    for _ in range(180):
        payload = client.get(f"{api}/jobs/{job_id}").raise_for_status().json()
        if payload["status"] == "succeeded":
            return payload
        if payload["status"] == "failed":
            raise RuntimeError(payload["error"])
        time.sleep(1)
    raise TimeoutError(job_id)


assert client.get(api.removesuffix("/api") + "/healthz").json()["status"] == "ok"
upload = client.post(
    f"{api}/images/upload",
    files=[
        ("files", ("one.png", image_bytes("#cfa671"), "image/png")),
        ("files", ("two.png", image_bytes("#9eb0a0"), "image/png")),
    ],
).raise_for_status().json()

batch_id = upload["batch_id"]
jobs = client.post(f"{api}/batches/{batch_id}/generate").raise_for_status().json()["jobs"]
for job in jobs:
    poll(job["id"])

image_id = upload["images"][0]["id"]
version_id = client.get(f"{api}/images/{image_id}/versions").raise_for_status().json()["active_version_id"]
edit = client.post(
    f"{api}/images/{image_id}/edit",
    json={"version_id": version_id, "user_prompt": "把衣服改成红色"},
).raise_for_status().json()
poll(edit["id"])

export = client.post(f"{api}/batches/{batch_id}/export", json={}).raise_for_status().json()
print("E2E_MOCK=PASS")
print(f"BATCH_ID={batch_id}")
print(f"ZIP_URL={export['zip_url']}")
PY
