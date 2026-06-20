from redis import Redis
from rq import Queue, SimpleWorker
from rq.serializers import JSONSerializer

from model_runtime.generator import preload_runtime as preload_generator
from model_runtime.sam_engine import preload_runtime as preload_sam
from services.api.app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    preload_generator()
    preload_sam()
    connection = Redis.from_url(settings.redis_url)
    worker = SimpleWorker(
        [Queue(settings.rq_queue_name, connection=connection, serializer=JSONSerializer())],
        connection=connection,
        serializer=JSONSerializer(),
    )
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
