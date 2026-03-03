import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "model_runtime"))

os.environ.setdefault("DATABASE_URL", "sqlite:///./runtime/test.db")
os.environ.setdefault("MEDIA_ROOT", "./runtime/test_media")
os.environ.setdefault("PUBLIC_MEDIA_BASE", "http://testserver/media")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
