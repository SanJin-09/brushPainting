import asyncio

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from services.api.app.core.config import Settings, get_settings
from services.api.app.core.security import require_api_access, validate_security_settings
from services.api.app.main import app

API_KEY = "d51c390ab35e4c48b60a08613e9b1741f72fd2059249687b04dba6f0ba5b1a33"
SESSION_SECRET = "acef320d4ce4a976d6d1290db73665f80ce51561a106a1748ccf772d8b00636b"
REDIS_PASSWORD = "e4c2ef4b86972cc32f9d735f17e9471cc5959370a4f42edc0189f98c973b992d"


def _settings(**overrides) -> Settings:
    values = {
        "APP_ENV": "development",
        "API_PUBLISH_HOST": "127.0.0.1",
        "API_AUTH_MODE": "disabled",
        "ALLOWED_ORIGINS": "http://127.0.0.1:5173",
        "ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
        "REDIS_URL": "redis://localhost:6379/0",
        "REDIS_PASSWORD": REDIS_PASSWORD,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_non_loopback_publish_requires_authentication():
    settings = _settings(API_PUBLISH_HOST="0.0.0.0")

    with pytest.raises(RuntimeError, match="必须设置 API_AUTH_MODE=api_key"):
        validate_security_settings(settings)


def test_production_rejects_weak_or_incomplete_security_settings():
    settings = _settings(
        APP_ENV="production",
        API_PUBLISH_HOST="0.0.0.0",
        API_AUTH_MODE="api_key",
        BRUSH_API_KEYS="short",
        API_SESSION_SECRET="short",
        API_SESSION_COOKIE_SECURE=False,
        API_DOCS_ENABLED=True,
        REDIS_PASSWORD="CHANGE_ME",
    )

    with pytest.raises(RuntimeError) as exc_info:
        validate_security_settings(settings)

    message = str(exc_info.value)
    assert "BRUSH_API_KEYS" in message
    assert "API_SESSION_SECRET" in message
    assert "API_SESSION_COOKIE_SECURE" in message
    assert "API_DOCS_ENABLED" in message
    assert "REDIS_PASSWORD" in message


def test_redis_password_must_not_be_embedded_in_url():
    settings = _settings(REDIS_URL="redis://:secret@localhost:6379/0")

    with pytest.raises(RuntimeError, match="不应内嵌密码"):
        validate_security_settings(settings)


def test_long_but_low_entropy_secret_is_rejected():
    settings = _settings(REDIS_PASSWORD="a" * 64)

    with pytest.raises(RuntimeError, match="足够随机"):
        validate_security_settings(settings)


def test_complete_production_security_configuration_is_accepted():
    settings = _settings(
        APP_ENV="production",
        API_PUBLISH_HOST="0.0.0.0",
        API_AUTH_MODE="api_key",
        BRUSH_API_KEYS=API_KEY,
        API_SESSION_SECRET=SESSION_SECRET,
        API_SESSION_COOKIE_SECURE=True,
        API_DOCS_ENABLED=False,
        ALLOWED_ORIGINS="https://paint.example.com",
        ALLOWED_HOSTS="paint.example.com,api.example.com",
    )

    validate_security_settings(settings)


def test_api_key_session_protects_api_and_media_without_loopback_bypass(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "api_key")
    monkeypatch.setenv("API_PUBLISH_HOST", "0.0.0.0")
    monkeypatch.setenv("BRUSH_API_KEYS", API_KEY)
    monkeypatch.setenv("API_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("API_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("REDIS_PASSWORD", REDIS_PASSWORD)
    get_settings.cache_clear()

    try:
        loopback_request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/batches/missing",
                "headers": [],
                "client": ("127.0.0.1", 50000),
                "server": ("testserver", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )
        with pytest.raises(HTTPException) as loopback_error:
            asyncio.run(require_api_access(loopback_request, None, None))
        assert loopback_error.value.status_code == 401

        client = TestClient(app)

        assert client.get("/healthz").status_code == 200
        assert client.get("/api/batches/missing").status_code == 401
        assert client.get("/media/uploads/missing.png").status_code == 401
        client.cookies.set("brush_session", "not-a-valid-session")
        assert client.get("/api/batches/missing").status_code == 401
        client.cookies.clear()

        invalid = client.post("/auth/session", headers={"X-API-Key": "wrong"})
        assert invalid.status_code == 401

        login = client.post("/auth/session", headers={"X-API-Key": API_KEY})
        assert login.status_code == 200
        csrf_token = login.json()["csrf_token"]
        assert csrf_token
        assert login.cookies.get("brush_session")

        status_response = client.get("/auth/status")
        assert status_response.json() == {
            "auth_required": True,
            "authenticated": True,
            "csrf_token": csrf_token,
        }
        assert client.get("/api/batches/missing").status_code == 404
        assert client.get("/media/uploads/missing.png").status_code == 404

        assert client.post("/api/images/upload").status_code == 403
        assert client.post(
            "/api/images/upload",
            headers={"X-CSRF-Token": csrf_token},
        ).status_code == 422

        logout = client.delete("/auth/session", headers={"X-CSRF-Token": csrf_token})
        assert logout.status_code == 204
        assert client.get("/api/batches/missing").status_code == 401
    finally:
        get_settings.cache_clear()


def test_direct_api_key_clients_do_not_need_browser_csrf(monkeypatch):
    monkeypatch.setenv("API_AUTH_MODE", "api_key")
    monkeypatch.setenv("API_PUBLISH_HOST", "0.0.0.0")
    monkeypatch.setenv("BRUSH_API_KEYS", API_KEY)
    monkeypatch.setenv("API_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("REDIS_PASSWORD", REDIS_PASSWORD)
    get_settings.cache_clear()

    try:
        client = TestClient(app)
        response = client.post("/api/images/upload", headers={"X-API-Key": API_KEY})
        assert response.status_code == 422
    finally:
        get_settings.cache_clear()


def test_host_allowlist_rejects_unknown_hosts():
    client = TestClient(app)

    assert client.get("/healthz", headers={"Host": "attacker.example"}).status_code == 400


def test_cors_preflight_only_allows_configured_frontend_origins():
    client = TestClient(app)
    headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-CSRF-Token",
    }

    allowed = client.options(
        "/api/images/upload",
        headers={**headers, "Origin": "http://127.0.0.1:5173"},
    )
    denied = client.options(
        "/api/images/upload",
        headers={**headers, "Origin": "https://attacker.example"},
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
