"""API Key 认证中间件"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Header, HTTPException, Request


@lru_cache(maxsize=1)
def _api_keys() -> set[str]:
    """从环境变量加载有效 API Key。"""
    import os

    raw = os.getenv("BRUSH_API_KEYS", "")
    if not raw:
        print("WARNING: BRUSH_API_KEYS is not set, authentication is disabled")
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


async def verify_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    """Dependency: 验证 API Key 或允许本地回环请求。"""
    # 允许本地请求（healthcheck、回环）
    if request.client and request.client.host in (
        "127.0.0.1",
        "::1",
    ):
        return

    keys = _api_keys()
    if not keys:
        return  # 未配置认证时允许所有请求

    if x_api_key not in keys:
        raise HTTPException(status_code=401, detail="无效的 API Key")