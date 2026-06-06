import pytest

import services.worker.tasks as tasks
from services.api.app.models.entities import Batch, ImageAsset, Job
from services.api.app.models.enums import ImageStatus, JobStatus, JobType


def test_generation_failure_is_recorded(db_session, monkeypatch):
    batch = Batch(id="batch")
    image = ImageAsset(
        id="image",
        batch=batch,
        original_filename="source.png",
        original_url="http://testserver/media/uploads/batch/image.png",
        thumbnail_url="http://testserver/media/thumbs/batch/image.jpg",
        width=100,
        height=100,
        status=ImageStatus.QUEUED.value,
    )
    job = Job(
        id="job",
        type=JobType.INITIAL.value,
        batch=batch,
        image=image,
        status=JobStatus.QUEUED.value,
        input_payload={"seed": 1},
    )
    db_session.add_all([batch, image, job])
    db_session.commit()
    monkeypatch.setattr(tasks.storage, "url_to_path", lambda _url: __file__)

    with pytest.raises(Exception):
        tasks.run_generation(job.id)

    db_session.expire_all()
    assert db_session.get(Job, job.id).status == JobStatus.FAILED.value
    assert db_session.get(Job, job.id).error
    assert db_session.get(ImageAsset, image.id).status == ImageStatus.FAILED.value
