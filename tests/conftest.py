import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "model_runtime"))

os.environ.setdefault("DATABASE_URL", "sqlite:///./runtime/test.db")
os.environ.setdefault("RUNTIME_ROOT", "./runtime/test_runtime")
os.environ.setdefault("PUBLIC_MEDIA_BASE", "http://testserver/media")
os.environ.setdefault("MODEL_BACKEND", "mock")
os.environ.setdefault("SAM3_BACKEND", "mock")
os.environ.setdefault("API_PUBLISH_HOST", "127.0.0.1")
os.environ.setdefault("API_AUTH_MODE", "disabled")
os.environ.setdefault("ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")

from services.api.app.db.database import SessionLocal, engine  # noqa: E402
from services.api.app.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def reset_state():
    runtime_root = ROOT / "runtime" / "test_runtime"
    if runtime_root.exists():
        shutil.rmtree(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)

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
