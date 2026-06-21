import pytest
from rq.serializers import JSONSerializer

import services.api.app.services.job_service as job_service
from services.api.app.models.entities import Batch, ImageAsset
from services.api.app.models.enums import JobType
from services.api.app.services.errors import ConflictError, ServiceUnavailableError


def _image(db_session) -> ImageAsset:
    batch = Batch(id="batch")
    image = ImageAsset(
        id="image",
        batch=batch,
        original_filename="source.png",
        original_url="http://testserver/media/uploads/batch/image.png",
        thumbnail_url="http://testserver/media/thumbs/batch/image.jpg",
        width=100,
        height=100,
    )
    db_session.add_all([batch, image])
    db_session.commit()
    return image


def test_database_rejects_two_active_jobs_for_same_image(db_session):
    image = _image(db_session)
    job_service.create_job(db_session, job_type=JobType.INITIAL.value, image=image, payload={"seed": 1})

    with pytest.raises(ConflictError):
        job_service.create_job(db_session, job_type=JobType.REGENERATE.value, image=image, payload={"seed": 2})


def test_dispatch_rejects_full_queue(monkeypatch):
    captured = {}

    class FullQueue:
        count = 50

        def __init__(self, *_args, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(job_service, "Queue", FullQueue)
    monkeypatch.setattr(job_service, "create_redis_connection", lambda _settings: object())

    with pytest.raises(ServiceUnavailableError, match="队列已满"):
        job_service.dispatch_job("job", JobType.SAM_SEGMENT.value)

    assert isinstance(captured["serializer"], JSONSerializer)
