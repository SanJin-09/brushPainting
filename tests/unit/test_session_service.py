import uuid

from sqlalchemy.orm import Session

from services.api.app.models.entities import ImageVersion, Session as SessionModel
from services.api.app.models.enums import ImageVersionKind, SessionStatus
from services.api.app.services.session_service import adopt_version


def test_adopt_version_keeps_single_current(db_session: Session):
    session_obj = SessionModel(
        id=str(uuid.uuid4()),
        source_image_url="http://testserver/media/sessions/demo/source.png",
        style_id="gongbi_default",
        status=SessionStatus.REVIEWING.value,
    )
    db_session.add(session_obj)
    db_session.flush()

    first = ImageVersion(
        id=str(uuid.uuid4()),
        session_id=session_obj.id,
        parent_version_id=None,
        kind=ImageVersionKind.FULL_RENDER.value,
        image_url="http://testserver/media/sessions/demo/versions/1.png",
        seed=1,
        params_hash="a",
        is_current=True,
    )
    second = ImageVersion(
        id=str(uuid.uuid4()),
        session_id=session_obj.id,
        parent_version_id=first.id,
        kind=ImageVersionKind.LOCAL_EDIT.value,
        image_url="http://testserver/media/sessions/demo/versions/2.png",
        seed=2,
        params_hash="b",
        is_current=False,
    )
    db_session.add_all([first, second])
    db_session.commit()

    updated = adopt_version(db_session, session_obj.id, second.id)
    currents = [version for version in updated.versions if version.is_current]

    assert len(currents) == 1
    assert currents[0].id == second.id
