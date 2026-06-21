from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse

from services.api.app.api.routes import router
from services.api.app.core.config import get_settings
from services.api.app.core.security import (
    auth_router,
    require_api_access,
    validate_security_settings,
)
from services.api.app.db.database import engine
from services.api.app.models import Base
from services.api.app.services.storage import LocalStorage

settings = get_settings()
validate_security_settings(settings)
storage = LocalStorage()
docs_enabled = settings.api_docs_enabled and settings.api_auth_mode.strip().lower() == "disabled"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Gongbi Repaint API",
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "X-CSRF-Token"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

app.include_router(auth_router)
app.include_router(router, dependencies=[Depends(require_api_access)])


@app.get(
    "/media/{path:path}",
    include_in_schema=False,
    dependencies=[Depends(require_api_access)],
)
def media(path: str):
    try:
        return FileResponse(storage.resolve_public_media(path))
    except ValueError:
        raise HTTPException(status_code=404, detail="媒体文件不存在")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
