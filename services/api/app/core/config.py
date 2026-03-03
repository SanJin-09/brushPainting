from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_port: int = Field(default=8000, alias="APP_PORT")

    database_url: str = Field(default="sqlite:///./runtime/dev.db", alias="DATABASE_URL")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/1", alias="CELERY_RESULT_BACKEND")

    media_root: str = Field(default="./runtime/media", alias="MEDIA_ROOT")
    public_media_base: str = Field(default="http://localhost:8000/media", alias="PUBLIC_MEDIA_BASE")

    style_config_path: str = Field(default="./configs/styles/gongbi_default.yaml", alias="STYLE_CONFIG_PATH")
    default_style_id: str = Field(default="gongbi_default", alias="DEFAULT_STYLE_ID")

    default_crop_count: int = Field(default=6, alias="DEFAULT_CROP_COUNT")
    min_crop_count: int = Field(default=4, alias="MIN_CROP_COUNT")
    max_crop_count: int = Field(default=8, alias="MAX_CROP_COUNT")
    min_area_ratio: float = Field(default=0.02, alias="MIN_AREA_RATIO")
    max_area_ratio: float = Field(default=0.35, alias="MAX_AREA_RATIO")
    max_overlap_iou: float = Field(default=0.2, alias="MAX_OVERLAP_IOU")

    sdxl_steps: int = Field(default=28, alias="SDXL_STEPS")
    sdxl_cfg: float = Field(default=6.5, alias="SDXL_CFG")
    sdxl_size: int = Field(default=1024, alias="SDXL_SIZE")
    controlnet_weight: float = Field(default=0.7, alias="CONTROLNET_WEIGHT")
    inpaint_steps: int = Field(default=24, alias="INPAINT_STEPS")
    inpaint_denoise: float = Field(default=0.45, alias="INPAINT_DENOISE")

    model_device: str = Field(default="cpu", alias="MODEL_DEVICE")
    model_precision: str = Field(default="fp16", alias="MODEL_PRECISION")
    model_root: str = Field(default="./runtime/models", alias="MODEL_ROOT")
    model_backend: str = Field(default="mock", alias="MODEL_BACKEND")

    @property
    def media_root_path(self) -> Path:
        return Path(self.media_root).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.media_root_path.mkdir(parents=True, exist_ok=True)
    return settings
