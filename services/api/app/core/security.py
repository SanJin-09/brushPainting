"""API 访问控制、短期会话与安全配置校验。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel

from services.api.app.core.config import Settings, get_settings

AUTH_MODE_DISABLED = "disabled"
AUTH_MODE_API_KEY = "api_key"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
WEAK_SECRETS = {
    "change_me",
    "changeme",
    "password",
    "replace_me",
    "replace-with-a-random-secret",
    "secret",
}
COOKIE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

auth_router = APIRouter(prefix="/auth", tags=["auth"])


class AuthStatusResponse(BaseModel):
    auth_required: bool
    authenticated: bool
    csrf_token: str | None = None


def _unauthorized(detail: str = "需要有效的 API Key") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "ApiKey"},
    )


def _secret_is_weak(value: str, *, minimum_length: int = 32) -> bool:
    normalized = value.strip().lower()
    return (
        len(value) < minimum_length
        or normalized in WEAK_SECRETS
        or len(set(value)) < 8
    )


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_security_settings(settings: Settings) -> None:
    """在服务启动前验证安全配置；危险组合直接拒绝启动。"""
    errors: list[str] = []
    app_env = settings.app_env.strip().lower()
    auth_mode = settings.api_auth_mode.strip().lower()
    redis_password = settings.redis_password.get_secret_value()
    session_secret = settings.api_session_secret.get_secret_value()

    if auth_mode not in {AUTH_MODE_DISABLED, AUTH_MODE_API_KEY}:
        errors.append("API_AUTH_MODE 仅支持 disabled 或 api_key")

    if auth_mode == AUTH_MODE_DISABLED and (
        app_env == "production" or not _is_loopback_host(settings.api_publish_host)
    ):
        errors.append("生产环境或非回环地址发布 API 时必须设置 API_AUTH_MODE=api_key")

    if auth_mode == AUTH_MODE_API_KEY:
        if not settings.api_keys:
            errors.append("API_AUTH_MODE=api_key 时必须设置 BRUSH_API_KEYS")
        elif any(_secret_is_weak(key) for key in settings.api_keys):
            errors.append("每个 BRUSH_API_KEYS 密钥必须至少 32 个字符、足够随机且不能使用默认占位值")

        if _secret_is_weak(session_secret):
            errors.append("API_SESSION_SECRET 必须至少 32 个字符、足够随机且不能使用默认占位值")
        elif session_secret in settings.api_keys:
            errors.append("API_SESSION_SECRET 不能与 BRUSH_API_KEYS 相同")

        if not settings.cors_origins or "*" in settings.cors_origins:
            errors.append("认证模式下 ALLOWED_ORIGINS 必须是明确的来源列表，不能使用通配符")

    if app_env == "production" and not settings.api_session_cookie_secure:
        errors.append("生产环境必须设置 API_SESSION_COOKIE_SECURE=true 并通过 HTTPS 访问")
    if app_env == "production" and settings.api_docs_enabled:
        errors.append("生产环境必须设置 API_DOCS_ENABLED=false")
    if app_env == "production" and any(
        not origin.lower().startswith("https://") for origin in settings.cors_origins
    ):
        errors.append("生产环境的 ALLOWED_ORIGINS 必须全部使用 HTTPS")

    if settings.api_session_ttl_seconds < 300 or settings.api_session_ttl_seconds > 86400:
        errors.append("API_SESSION_TTL_SECONDS 必须位于 300 到 86400 秒之间")

    if not COOKIE_NAME_PATTERN.fullmatch(settings.api_session_cookie_name):
        errors.append("API_SESSION_COOKIE_NAME 只能包含字母、数字、下划线和连字符")

    if urlsplit(settings.redis_url).password:
        errors.append("REDIS_URL 不应内嵌密码，请使用独立的 REDIS_PASSWORD")
    if app_env == "production" and not redis_password:
        errors.append("生产环境必须设置 REDIS_PASSWORD")
    if redis_password and _secret_is_weak(redis_password):
        errors.append("REDIS_PASSWORD 必须至少 32 个字符、足够随机且不能使用默认占位值")

    if not settings.trusted_hosts or "*" in settings.trusted_hosts:
        errors.append("ALLOWED_HOSTS 必须是明确的主机列表，不能使用通配符")

    if errors:
        raise RuntimeError("安全配置无效:\n- " + "\n- ".join(errors))


def _matches_api_key(candidate: str | None, settings: Settings) -> str | None:
    if not candidate:
        return None
    for configured_key in settings.api_keys:
        if hmac.compare_digest(candidate, configured_key):
            return configured_key
    return None


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:24]


def _encode_payload(payload: dict[str, object], secret: str) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(body).rstrip(b"=")
    signature = hmac.new(secret.encode("utf-8"), encoded, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{encoded.decode('ascii')}.{encoded_signature.decode('ascii')}"


def _decode_payload(token: str, settings: Settings) -> dict[str, object] | None:
    try:
        encoded, encoded_signature = token.split(".", 1)
        secret = settings.api_session_secret.get_secret_value()
        expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
        provided = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        if not hmac.compare_digest(expected, provided):
            return None
        body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(body)
    except (binascii.Error, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    expires_at = payload.get("exp")
    fingerprint = payload.get("kid")
    csrf_token = payload.get("csrf")
    if not isinstance(expires_at, int) or expires_at <= int(time.time()):
        return None
    if not isinstance(fingerprint, str) or not isinstance(csrf_token, str):
        return None
    valid_fingerprints = {_key_fingerprint(key) for key in settings.api_keys}
    if fingerprint not in valid_fingerprints:
        return None
    return payload


def _create_session(api_key: str, settings: Settings) -> tuple[str, str]:
    csrf_token = secrets.token_urlsafe(32)
    payload: dict[str, object] = {
        "v": 1,
        "kid": _key_fingerprint(api_key),
        "csrf": csrf_token,
        "exp": int(time.time()) + settings.api_session_ttl_seconds,
    }
    return _encode_payload(payload, settings.api_session_secret.get_secret_value()), csrf_token


def _cookie_payload(request: Request, settings: Settings) -> dict[str, object] | None:
    token = request.cookies.get(settings.api_session_cookie_name)
    if not token:
        return None
    return _decode_payload(token, settings)


async def require_api_access(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    """允许直接 API Key 或短期浏览器会话；不根据客户端 IP 绕过认证。"""
    settings = get_settings()
    if settings.api_auth_mode.strip().lower() == AUTH_MODE_DISABLED:
        return

    if _matches_api_key(x_api_key, settings):
        return

    payload = _cookie_payload(request, settings)
    if payload is None:
        raise _unauthorized()

    if request.method.upper() not in SAFE_METHODS:
        expected_csrf = payload["csrf"]
        if not isinstance(expected_csrf, str) or not x_csrf_token or not hmac.compare_digest(
            x_csrf_token,
            expected_csrf,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF 校验失败",
            )


@auth_router.get("/status", response_model=AuthStatusResponse)
def auth_status(request: Request) -> AuthStatusResponse:
    settings = get_settings()
    if settings.api_auth_mode.strip().lower() == AUTH_MODE_DISABLED:
        return AuthStatusResponse(auth_required=False, authenticated=True)

    payload = _cookie_payload(request, settings)
    csrf_token = payload.get("csrf") if payload else None
    return AuthStatusResponse(
        auth_required=True,
        authenticated=payload is not None,
        csrf_token=csrf_token if isinstance(csrf_token, str) else None,
    )


@auth_router.post("/session", response_model=AuthStatusResponse)
def create_auth_session(
    response: Response,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AuthStatusResponse:
    settings = get_settings()
    if settings.api_auth_mode.strip().lower() == AUTH_MODE_DISABLED:
        return AuthStatusResponse(auth_required=False, authenticated=True)

    api_key = _matches_api_key(x_api_key, settings)
    if api_key is None:
        raise _unauthorized("API Key 无效")

    token, csrf_token = _create_session(api_key, settings)
    response.set_cookie(
        key=settings.api_session_cookie_name,
        value=token,
        max_age=settings.api_session_ttl_seconds,
        httponly=True,
        secure=settings.api_session_cookie_secure,
        samesite="strict",
        path="/",
    )
    return AuthStatusResponse(
        auth_required=True,
        authenticated=True,
        csrf_token=csrf_token,
    )


@auth_router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_access)],
)
def delete_auth_session(response: Response) -> Response:
    settings = get_settings()
    response.delete_cookie(
        key=settings.api_session_cookie_name,
        path="/",
        secure=settings.api_session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
