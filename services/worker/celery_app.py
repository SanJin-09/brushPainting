from celery import Celery

from services.api.app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "gongbi_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_default_queue="default",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
)

celery_app.autodiscover_tasks(["services.worker"])

# Ensure task registration even when autodiscovery order differs.
import services.worker.tasks  # noqa: E402,F401
