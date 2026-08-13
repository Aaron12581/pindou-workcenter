import os
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


_service_root = Path(__file__).resolve().parents[1]
_default_data_root = Path(".data")
_data_root = Path(os.environ.get("PERLER_DATA_ROOT", _default_data_root)).expanduser()


class Settings(BaseSettings):
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    dashscope_api_key: SecretStr | None = Field(default=None, validation_alias="DASHSCOPE_API_KEY")
    dashscope_workspace_id: str | None = Field(default=None, validation_alias="DASHSCOPE_WORKSPACE_ID")
    image_provider: str = "openai"
    image_model: str = "gpt-image-2"
    vision_model: str = "qwen3-vl-flash"
    pattern_ai_mode: str = "auto"
    # The desktop application supplies PERLER_DATA_ROOT inside the user's
    # Application Support directory.  Keeping the legacy relative default
    # preserves command-line project compatibility.
    database_url: str = f"sqlite:///{_data_root / 'perler.db'}"
    storage_root: Path = _data_root / "uploads"
    backup_root: Path = _data_root / "backups"
    export_root: Path = _data_root / "exports"
    desktop_mode: bool = False
    cors_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://localhost:4173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:4173",
    )
    max_upload_bytes: int = 20 * 1024 * 1024
    max_backup_bytes: int = 250 * 1024 * 1024
    allowed_mime_types: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
    )
    model_config = SettingsConfigDict(
        env_prefix="PERLER_",
        # PERLER_ENV_FILE allows the packaged desktop application to retain
        # credentials outside its read-only .app bundle.
        env_file=Path(os.environ.get("PERLER_ENV_FILE", _service_root / ".env")),
        extra="ignore",
    )


settings = Settings()
