from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from services.api.app.api.routes import router
from services.api.app.core.config import get_settings
from services.api.app.core.security import verify_api_key
from services.api.app.db.database import engine
from services.api.app.models import Base
from services.api.app.services.storage import LocalStorage

settings = get_settings()
storage = LocalStorage()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Gongbi Repaint API",
    version="0.2.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_api_key)],
)

origins = [
    o.strip()
    for o in settings.allowed_origins.split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(router)

@app.get("/media/{path:path}", include_in_schema=False)
def media(path: str):
    try:
        return FileResponse(storage.resolve_public_media(path))
    except ValueError:
        raise HTTPException(status_code=404, detail="媒体文件不存在")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
