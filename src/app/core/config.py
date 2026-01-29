from __future__ import annotations

from pathlib import Path

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..schemas.EnvironmentOption import EnvironmentOption


class _SettingsBase(BaseSettings):
    """Common settings configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="",
    )


class AppSettings(_SettingsBase):
    APP_NAME: str = "FastAPI app"
    APP_DESCRIPTION: str | None = None
    APP_VERSION: str | None = None
    LICENSE_NAME: str | None = None
    CONTACT_NAME: str | None = None
    CONTACT_EMAIL: str | None = None


class EnvironmentSettings(_SettingsBase):
    ENVIRONMENT: EnvironmentOption = Field(default=EnvironmentOption.LOCAL)


class RedisCacheSettings(_SettingsBase):
    REDIS_CACHE_HOST: str = "localhost"
    REDIS_CACHE_PORT: int = 6379

    @computed_field  # type: ignore[misc]
    @property
    def REDIS_CACHE_URL(self) -> str:
        return f"redis://{self.REDIS_CACHE_HOST}:{self.REDIS_CACHE_PORT}"

    @field_validator("REDIS_CACHE_HOST")
    @classmethod
    def _host_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("REDIS_CACHE_HOST must be a non-empty string")
        return v.strip()

    @field_validator("REDIS_CACHE_PORT")
    @classmethod
    def _port_range(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("REDIS_CACHE_PORT must be in [1, 65535]")
        return v


class ClientSideCacheSettings(_SettingsBase):
    CLIENT_CACHE_MAX_AGE: int = 60

    @field_validator("CLIENT_CACHE_MAX_AGE")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("CLIENT_CACHE_MAX_AGE must be >= 0")
        return v


class LogSettings(_SettingsBase):
    """
    Настройки логирования приложения.

    :ivar APP_TZ_OFFSET: Смещение часового пояса в часах для временных меток логов.
    :ivar APP_LOG_DIR: Директория для хранения лог-файлов.
    :ivar LOG_MAX_BYTES: Максимальный размер одного лог-файла в байтах.
    :ivar LOG_BACKUP_COUNT: Количество ротируемых резервных копий лог-файлов.
    """

    APP_TZ_OFFSET: int = 3
    APP_LOG_DIR: Path = Field(default_factory=lambda: Path.cwd() / "logs")
    LOG_MAX_BYTES: int = 10_485_760  # 10 MB
    LOG_BACKUP_COUNT: int = 2

    @field_validator("APP_TZ_OFFSET")
    @classmethod
    def _tz_offset_range(cls, v: int) -> int:
        if not (-12 <= v <= 14):
            raise ValueError("APP_TZ_OFFSET must be in [-12, 14]")
        return v

    @field_validator("APP_LOG_DIR")
    @classmethod
    def _resolve_and_create_log_dir(cls, v: Path) -> Path:
        resolved = v.resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    @field_validator("LOG_MAX_BYTES")
    @classmethod
    def _max_bytes_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("LOG_MAX_BYTES must be >= 1")
        return v

    @field_validator("LOG_BACKUP_COUNT")
    @classmethod
    def _backup_count_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("LOG_BACKUP_COUNT must be >= 0")
        return v

    @computed_field  # type: ignore[misc]
    @property
    def SYSTEM_LOG_PATH(self) -> Path:
        """Путь к файлу системных логов."""
        return self.APP_LOG_DIR / "system.log"

    @computed_field  # type: ignore[misc]
    @property
    def PERSONAL_LOG_PATH(self) -> Path:
        """Путь к файлу персональных логов."""
        return self.APP_LOG_DIR / "personal.log"


class Settings(
    AppSettings,
    EnvironmentSettings,
    RedisCacheSettings,
    ClientSideCacheSettings,
    LogSettings,
):
    pass


settings = Settings()
