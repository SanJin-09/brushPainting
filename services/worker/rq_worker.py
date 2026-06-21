from rq import Queue, SimpleWorker
from rq.serializers import JSONSerializer

from model_runtime.generator import preload_runtime as preload_generator
from model_runtime.sam_engine import preload_runtime as preload_sam
from services.api.app.core.config import get_settings
from services.api.app.core.redis_client import create_redis_connection
from services.api.app.core.security import validate_security_settings


def main() -> None:
    settings = get_settings()
    validate_security_settings(settings)
    preload_generator()
    preload_sam()
    connection = create_redis_connection(settings)
    worker = SimpleWorker(
        [Queue(settings.rq_queue_name, connection=connection, serializer=JSONSerializer())],
        connection=connection,
        serializer=JSONSerializer(),
    )
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
