from pathlib import Path

from rq.serializers import JSONSerializer
import yaml

from services.api.app.core.config import Settings
import services.api.app.core.redis_client as redis_client
import services.worker.rq_worker as rq_worker


def test_worker_uses_json_serializer(monkeypatch):
    captured = {}

    class FakeQueue:
        def __init__(self, *_args, **kwargs):
            captured["queue_serializer"] = kwargs["serializer"]

    class FakeWorker:
        def __init__(self, _queues, **kwargs):
            captured["worker_serializer"] = kwargs["serializer"]

        def work(self, **kwargs):
            captured["work"] = kwargs

    monkeypatch.setattr(rq_worker, "preload_generator", lambda: None)
    monkeypatch.setattr(rq_worker, "preload_sam", lambda: None)
    monkeypatch.setattr(rq_worker, "create_redis_connection", lambda _settings: object())
    monkeypatch.setattr(rq_worker, "Queue", FakeQueue)
    monkeypatch.setattr(rq_worker, "SimpleWorker", FakeWorker)

    rq_worker.main()

    assert isinstance(captured["queue_serializer"], JSONSerializer)
    assert isinstance(captured["worker_serializer"], JSONSerializer)
    assert captured["work"] == {"with_scheduler": False}


def test_redis_password_is_passed_separately_from_url(monkeypatch):
    captured = {}
    settings = Settings(
        _env_file=None,
        REDIS_URL="redis://redis:6379/0",
        REDIS_PASSWORD="r" * 40,
    )

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(redis_client.Redis, "from_url", fake_from_url)

    redis_client.create_redis_connection(settings)

    assert captured == {
        "url": "redis://redis:6379/0",
        "kwargs": {"password": "r" * 40},
    }


def test_compose_does_not_publish_redis_beyond_loopback():
    repository_root = Path(__file__).resolve().parents[2]
    compose_path = repository_root / "infra" / "docker" / "docker-compose.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)

    assert "CHANGE_ME" not in compose_text
    assert compose["services"]["redis"]["ports"] == [
        "127.0.0.1:${REDIS_HOST_PORT:-6380}:6379"
    ]
    assert '$$REDIS_PASSWORD' in compose["services"]["redis"]["command"][-1]
    backend_environment = compose["services"]["api"]["environment"]
    assert backend_environment["REDIS_URL"] == "redis://redis:6379/0"
    assert "REDIS_PASSWORD" in backend_environment

    api_dockerfile = (repository_root / "infra" / "docker" / "api.Dockerfile").read_text()
    assert "${API_LISTEN_HOST:-127.0.0.1}" in api_dockerfile
