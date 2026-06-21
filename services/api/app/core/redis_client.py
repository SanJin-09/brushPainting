from redis import Redis

from services.api.app.core.config import Settings, get_settings


def create_redis_connection(settings: Settings | None = None) -> Redis:
    resolved = settings or get_settings()
    password = resolved.redis_password.get_secret_value()
    kwargs = {"password": password} if password else {}
    return Redis.from_url(resolved.redis_url, **kwargs)
