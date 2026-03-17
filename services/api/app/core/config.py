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
    reference_scrape_root: str = Field(default="./runtime/reference_scrape", alias="REFERENCE_SCRAPE_ROOT")

    style_config_path: str = Field(default="./configs/styles/gongbi_default.yaml", alias="STYLE_CONFIG_PATH")
    default_style_id: str = Field(default="gongbi_default", alias="DEFAULT_STYLE_ID")

    z_image_model_path: str = Field(default="./runtime/models/z_image", alias="Z_IMAGE_MODEL_PATH")
    z_image_steps: int = Field(default=32, alias="Z_IMAGE_STEPS")
    z_image_size: int = Field(default=1536, alias="Z_IMAGE_SIZE")
    z_image_cfg: float = Field(default=4.0, alias="Z_IMAGE_CFG")
    z_image_img2img_strength: float = Field(default=0.6, alias="Z_IMAGE_IMG2IMG_STRENGTH")
    z_image_inpaint_strength: float = Field(default=1.0, alias="Z_IMAGE_INPAINT_STRENGTH")
    inpaint_context_pad: int = Field(default=96, alias="INPAINT_CONTEXT_PAD")
    inpaint_mask_feather: int = Field(default=16, alias="INPAINT_MASK_FEATHER")
    mask_assist_backend: str = Field(default="mock", alias="MASK_ASSIST_BACKEND")
    sam_model_path: str = Field(default="./runtime/models/sam/sam_vit_b.pth", alias="SAM_MODEL_PATH")

    model_device: str = Field(default="cpu", alias="MODEL_DEVICE")
    model_precision: str = Field(default="bf16", alias="MODEL_PRECISION")
    model_root: str = Field(default="./runtime/models", alias="MODEL_ROOT")
    model_backend: str = Field(default="zimage", alias="MODEL_BACKEND")

    @property
    def media_root_path(self) -> Path:
        return Path(self.media_root).resolve()

    @property
    def reference_scrape_root_path(self) -> Path:
        return Path(self.reference_scrape_root).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.media_root_path.mkdir(parents=True, exist_ok=True)
    settings.reference_scrape_root_path.mkdir(parents=True, exist_ok=True)
    return settings
