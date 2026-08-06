from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "tg-sgk"
    api_key: str = Field(default="change-me", alias="TG_SGK_API_KEY")

    tg_api_id: int | None = Field(default=None, alias="TG_API_ID")
    tg_api_hash: str | None = Field(default=None, alias="TG_API_HASH")
    tg_phone: str | None = Field(default=None, alias="TG_PHONE")
    tg_session_path: str = Field(default="/data/telegram-user", alias="TG_SESSION_PATH")
    tg_mock: bool = Field(default=False, alias="TG_MOCK")

    data_dir: Path = Field(default=Path("/data"), alias="TG_SGK_DATA_DIR")
    database_path: Path = Field(
        default=Path("/data/tg-sgk.sqlite3"), alias="TG_SGK_DATABASE_PATH"
    )
    min_action_interval_seconds: float = Field(
        default=1.5, ge=0, le=60, alias="TG_SGK_MIN_ACTION_INTERVAL_SECONDS"
    )
    default_timeout_seconds: float = Field(
        default=30, ge=1, le=300, alias="TG_SGK_DEFAULT_TIMEOUT_SECONDS"
    )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        Path(self.tg_session_path).parent.mkdir(parents=True, exist_ok=True)
