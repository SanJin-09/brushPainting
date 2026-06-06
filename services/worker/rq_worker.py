from redis import Redis
from rq import Queue, SimpleWorker

from model_runtime.generator import preload_runtime
from services.api.app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    preload_runtime()
    connection = Redis.from_url(settings.redis_url)
    worker = SimpleWorker([Queue(settings.rq_queue_name, connection=connection)], connection=connection)
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
