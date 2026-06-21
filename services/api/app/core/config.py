from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_port: int = Field(default=8000, alias="APP_PORT")
    api_publish_host: str = Field(default="127.0.0.1", alias="API_PUBLISH_HOST")
    api_auth_mode: str = Field(default="disabled", alias="API_AUTH_MODE")
    brush_api_keys: SecretStr = Field(default=SecretStr(""), alias="BRUSH_API_KEYS")
    api_session_secret: SecretStr = Field(default=SecretStr(""), alias="API_SESSION_SECRET")
    api_session_ttl_seconds: int = Field(default=12 * 60 * 60, alias="API_SESSION_TTL_SECONDS")
    api_session_cookie_name: str = Field(default="brush_session", alias="API_SESSION_COOKIE_NAME")
    api_session_cookie_secure: bool = Field(default=False, alias="API_SESSION_COOKIE_SECURE")
    api_docs_enabled: bool = Field(default=True, alias="API_DOCS_ENABLED")
    database_url: str = Field(default="sqlite:///./runtime/db.sqlite", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_password: SecretStr = Field(default=SecretStr(""), alias="REDIS_PASSWORD")
    rq_queue_name: str = Field(default="gpu", alias="RQ_QUEUE_NAME")
    rq_max_queued_jobs: int = Field(default=50, alias="RQ_MAX_QUEUED_JOBS")

    runtime_root: str = Field(default="./runtime", alias="RUNTIME_ROOT")
    public_media_base: str = Field(default="http://localhost:8000/media", alias="PUBLIC_MEDIA_BASE")
    reference_scrape_root: str = Field(default="./runtime/reference_scrape", alias="REFERENCE_SCRAPE_ROOT")

    max_upload_files: int = Field(default=5, alias="MAX_UPLOAD_FILES")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    max_image_edge: int = Field(default=8192, alias="MAX_IMAGE_EDGE")
    thumbnail_max_edge: int = Field(default=480, alias="THUMBNAIL_MAX_EDGE")

    model_backend: str = Field(default="mock", alias="MODEL_BACKEND")
    model_device: str = Field(default="cuda", alias="MODEL_DEVICE")
    qwen_edit_model_path: str = Field(default="/models/qwen_image_edit_2511", alias="QWEN_EDIT_MODEL_PATH")
    qwen_image_components_path: str = Field(default="/models/qwen_image", alias="QWEN_IMAGE_COMPONENTS_PATH")
    qwen_edit_processor_path: str = Field(default="/models/qwen_image_edit/processor", alias="QWEN_EDIT_PROCESSOR_PATH")
    gongbi_lora_path: str = Field(
        default="/models/lora/qwen_image_edit_2511_gongbi_lora_v1.safetensors",
        alias="GONGBI_LORA_PATH",
    )
    gongbi_lora_scale: float = Field(default=1.0, alias="GONGBI_LORA_SCALE")
    qwen_image_steps: int = Field(default=40, alias="QWEN_IMAGE_STEPS")

    allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="ALLOWED_ORIGINS",
    )
    allowed_hosts: str = Field(
        default="localhost,127.0.0.1,::1,testserver",
        alias="ALLOWED_HOSTS",
    )

    # SAM 3
    sam3_backend: str = Field(default="mock", alias="SAM3_BACKEND")
    sam3_preload: bool = Field(default=False, alias="SAM3_PRELOAD")
    sam3_model_source: str = Field(default="local", alias="SAM3_MODEL_SOURCE")
    sam3_checkpoint_path: str = Field(default="/models/sam3/sam3.pt", alias="SAM3_CHECKPOINT_PATH")
    sam3_modelscope_model_id: str = Field(default="facebook/sam3", alias="SAM3_MODELSCOPE_MODEL_ID")
    sam3_modelscope_revision: str = Field(default="master", alias="SAM3_MODELSCOPE_REVISION")
    sam3_modelscope_local_dir: str = Field(
        default="./runtime/models/sam3",
        alias="SAM3_MODELSCOPE_LOCAL_DIR",
    )
    sam3_modelscope_checkpoint_filename: str = Field(
        default="sam3.pt",
        alias="SAM3_MODELSCOPE_CHECKPOINT_FILENAME",
    )
    sam3_modelscope_download_full: bool = Field(
        default=False,
        alias="SAM3_MODELSCOPE_DOWNLOAD_FULL",
    )
    sam3_device: str = Field(default="cuda", alias="SAM3_DEVICE")
    sam3_amp_dtype: str = Field(default="bfloat16", alias="SAM3_AMP_DTYPE")
    sam3_score_threshold: float = Field(default=0.30, alias="SAM3_SCORE_THRESHOLD")
    segment_max_results: int = Field(default=12, alias="SEGMENT_MAX_RESULTS")
    segment_min_area_ratio: float = Field(default=0.015, alias="SEGMENT_MIN_AREA_RATIO")

    @property
    def runtime_root_path(self) -> Path:
        return Path(self.runtime_root).resolve()

    @property
    def reference_scrape_root_path(self) -> Path:
        return Path(self.reference_scrape_root).resolve()

    @property
    def api_keys(self) -> tuple[str, ...]:
        raw = self.brush_api_keys.get_secret_value()
        return tuple(key.strip() for key in raw.split(",") if key.strip())

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.runtime_root_path.mkdir(parents=True, exist_ok=True)
    settings.reference_scrape_root_path.mkdir(parents=True, exist_ok=True)
    return settings
