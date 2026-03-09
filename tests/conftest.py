import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "model_runtime"))

os.environ.setdefault("DATABASE_URL", "sqlite:///./runtime/test.db")
os.environ.setdefault("MEDIA_ROOT", "./runtime/test_media")
os.environ.setdefault("PUBLIC_MEDIA_BASE", "http://testserver/media")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
os.environ.setdefault("MODEL_BACKEND", "mock")
os.environ.setdefault("MASK_ASSIST_BACKEND", "mock")

from services.api.app.db.database import SessionLocal, engine  # noqa: E402
from services.api.app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def reset_state():
    media_root = ROOT / "runtime" / "test_media"
    if media_root.exists():
        shutil.rmtree(media_root)
    media_root.mkdir(parents=True, exist_ok=True)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
