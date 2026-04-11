from __future__ import annotations

import threading

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..schemas.EnvironmentOption import EnvironmentOption


class _SettingsBase(BaseSettings):
    """Базовый класс конфигурации приложения."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="",
    )


class AppSettings(_SettingsBase):
    """Общие настройки приложения."""

    APP_NAME: str = "FastAPI app"
    APP_DESCRIPTION: str | None = None
    APP_VERSION: str | None = None
    LICENSE_NAME: str | None = None
    CONTACT_NAME: str | None = None
    CONTACT_EMAIL: str | None = None


class EnvironmentSettings(_SettingsBase):
    """Настройки окружения."""

    ENVIRONMENT: EnvironmentOption = Field(default=EnvironmentOption.LOCAL)


class RedisCacheSettings(_SettingsBase):
    """Настройки подключения к Redis для кэширования."""

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
    """Настройки клиентского кэширования (HTTP-заголовки)."""

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
    def _resolve_log_dir(cls, v: Path) -> Path:
        return v.resolve()

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


class LiteLLMSettings(_SettingsBase):
    """
    Настройки для подключения к LiteLLM.

    :ivar LITELLM_BASE_URL: Базовый URL LiteLLM API.
    :ivar LITELLM_API_KEY: API ключ для аутентификации (None — не задан).
    :ivar LITELLM_MODEL: Имя модели по умолчанию.
    :ivar LITELLM_TIMEOUT: Таймаут запросов в секундах.
    :ivar LITELLM_MAX_RETRIES: Максимальное количество повторных попыток.
    :ivar LITELLM_RETRY_BACKOFF_BASE: Базовая задержка для экспоненциального backoff (секунды).
    :ivar LITELLM_RETRY_BACKOFF_MAX: Максимальная задержка для экспоненциального backoff (секунды).
    :ivar LITELLM_MODELS_FETCH_TIMEOUT: Таймаут запроса списка доступных моделей (секунды).
    """

    LITELLM_BASE_URL: str = "http://localhost:4000"
    LITELLM_API_KEY: str | None = None
    LITELLM_MODEL: str = "local_llm"
    LITELLM_TIMEOUT: int = 120
    LITELLM_MAX_RETRIES: int = 3
    LITELLM_RETRY_BACKOFF_BASE: float = 0.5
    LITELLM_RETRY_BACKOFF_MAX: float = 30.0
    LITELLM_MODELS_FETCH_TIMEOUT: float = 10.0
    LITELLM_HEALTH_CHECK_TIMEOUT: float = 5.0
    LITELLM_CIRCUIT_BREAKER_THRESHOLD: int = 5
    LITELLM_CIRCUIT_BREAKER_RECOVERY: float = 60.0

    @field_validator("LITELLM_BASE_URL")
    @classmethod
    def _url_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("LITELLM_BASE_URL must be a non-empty string")
        return v.strip().rstrip("/")

    @field_validator("LITELLM_TIMEOUT")
    @classmethod
    def _timeout_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("LITELLM_TIMEOUT must be >= 1")
        return v

    @field_validator("LITELLM_MAX_RETRIES")
    @classmethod
    def _retries_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("LITELLM_MAX_RETRIES must be >= 0")
        return v

    @field_validator("LITELLM_RETRY_BACKOFF_BASE")
    @classmethod
    def _backoff_base_positive(cls, v: float) -> float:
        """Проверяет, что базовая задержка backoff положительна."""
        if v <= 0:
            raise ValueError("LITELLM_RETRY_BACKOFF_BASE must be > 0")
        return v

    @field_validator("LITELLM_RETRY_BACKOFF_MAX")
    @classmethod
    def _backoff_max_positive(cls, v: float) -> float:
        """Проверяет, что максимальная задержка backoff положительна."""
        if v <= 0:
            raise ValueError("LITELLM_RETRY_BACKOFF_MAX must be > 0")
        return v

    @field_validator("LITELLM_MODELS_FETCH_TIMEOUT")
    @classmethod
    def _models_fetch_timeout_positive(cls, v: float) -> float:
        """Проверяет, что таймаут получения списка моделей положителен."""
        if v <= 0:
            raise ValueError("LITELLM_MODELS_FETCH_TIMEOUT must be > 0")
        return v

    @field_validator("LITELLM_HEALTH_CHECK_TIMEOUT")
    @classmethod
    def _health_check_timeout_positive(cls, v: float) -> float:
        """Проверяет, что таймаут health check положителен."""
        if v <= 0:
            raise ValueError("LITELLM_HEALTH_CHECK_TIMEOUT must be > 0")
        return v

    @field_validator("LITELLM_CIRCUIT_BREAKER_THRESHOLD")
    @classmethod
    def _cb_threshold_positive(cls, v: int) -> int:
        """Проверяет, что порог circuit breaker положителен."""
        if v < 1:
            raise ValueError("LITELLM_CIRCUIT_BREAKER_THRESHOLD must be >= 1")
        return v

    @field_validator("LITELLM_CIRCUIT_BREAKER_RECOVERY")
    @classmethod
    def _cb_recovery_positive(cls, v: float) -> float:
        """Проверяет, что таймаут восстановления circuit breaker положителен."""
        if v <= 0:
            raise ValueError("LITELLM_CIRCUIT_BREAKER_RECOVERY must be > 0")
        return v


class InterviewSettings(_SettingsBase):
    """
    Настройки интервью-сессии.

    :ivar INTERVIEW_LOG_DIR: Директория для хранения логов интервью.
    :ivar TEAM_NAME: Название команды для логов.
    :ivar MAX_TURNS: Максимальное количество ходов в интервью.
    :ivar HISTORY_WINDOW_TURNS: Количество последних ходов, передаваемых в контекст LLM Interviewer.
    :ivar GREETING_MAX_TOKENS: Максимальное количество токенов для генерации приветствия.
    """

    INTERVIEW_LOG_DIR: Path = Field(default_factory=lambda: Path.cwd() / "interview_logs")
    TEAM_NAME: str = "Interview Coach Team"
    MAX_TURNS: int = 20
    HISTORY_WINDOW_TURNS: int = 10
    GREETING_MAX_TOKENS: int = 300

    @field_validator("INTERVIEW_LOG_DIR")
    @classmethod
    def _resolve_interview_log_dir(cls, v: Path) -> Path:
        return v.resolve()

    @field_validator("MAX_TURNS")
    @classmethod
    def _max_turns_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("MAX_TURNS must be >= 1")
        return v

    @field_validator("HISTORY_WINDOW_TURNS")
    @classmethod
    def _history_window_positive(cls, v: int) -> int:
        """Проверяет, что окно истории положительно."""
        if v < 1:
            raise ValueError("HISTORY_WINDOW_TURNS must be >= 1")
        return v

    @field_validator("GREETING_MAX_TOKENS")
    @classmethod
    def _greeting_max_tokens_positive(cls, v: int) -> int:
        """Проверяет, что макс. токенов приветствия положительно."""
        if v < 1:
            raise ValueError("GREETING_MAX_TOKENS must be >= 1")
        return v


class LangfuseSettings(_SettingsBase):
    """
    Настройки для Langfuse observability (self-hosted / локальный).

    :ivar LANGFUSE_ENABLED: Включить/выключить Langfuse трекинг.
    :ivar LANGFUSE_PUBLIC_KEY: Публичный ключ Langfuse (None — не задан).
    :ivar LANGFUSE_SECRET_KEY: Секретный ключ Langfuse (None — не задан).
    :ivar LANGFUSE_HOST: URL хоста Langfuse (локальный по умолчанию).
    """

    LANGFUSE_ENABLED: bool = True
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "http://localhost:3000"

    @field_validator("LANGFUSE_HOST")
    @classmethod
    def _host_strip(cls, v: str) -> str:
        return v.strip().rstrip("/") if v else "http://localhost:3000"


class LLMCacheSettings(_SettingsBase):
    """
    Настройки кэширования LLM-ответов.

    :ivar LLM_CACHE_ENABLED: Включить/выключить кэширование ответов LLM.
    :ivar LLM_CACHE_TTL_SECONDS: Время жизни кэшированного ответа в секундах.
    """

    LLM_CACHE_ENABLED: bool = False
    LLM_CACHE_TTL_SECONDS: int = 3600

    @model_validator(mode="after")
    def _validate_ttl_when_enabled(self) -> LLMCacheSettings:
        """Проверяет, что TTL кэша положителен, если кэширование включено."""
        if self.LLM_CACHE_ENABLED and self.LLM_CACHE_TTL_SECONDS < 1:
            raise ValueError(
                "LLM_CACHE_TTL_SECONDS must be >= 1 when LLM_CACHE_ENABLED is True"
            )
        return self


class GradioUISettings(_SettingsBase):
    """
    Настройки Gradio-интерфейса.

    Содержит параметры компоновки UI, диапазоны слайдеров
    и значения по умолчанию для параметров агентов в интерфейсе.

    :ivar UI_CHAT_HEIGHT: Высота окна чата в пикселях.
    :ivar UI_MSG_INPUT_LINES: Количество строк поля ввода сообщения.
    :ivar UI_MSG_INPUT_MAX_LINES: Максимальное количество строк поля ввода сообщения.
    :ivar UI_JOB_DESC_LINES: Количество строк поля описания вакансии.
    :ivar UI_JOB_DESC_MAX_LINES: Максимальное количество строк поля описания вакансии.
    :ivar UI_FEEDBACK_LINES: Количество строк поля фидбэка.
    :ivar UI_FEEDBACK_MAX_LINES: Максимальное количество строк поля фидбэка.
    :ivar UI_TEMPERATURE_MIN: Минимальное значение слайдера температуры.
    :ivar UI_TEMPERATURE_MAX: Максимальное значение слайдера температуры.
    :ivar UI_TEMPERATURE_STEP: Шаг слайдера температуры.
    :ivar UI_TOKENS_MIN: Минимальное значение слайдера токенов (Observer, Interviewer).
    :ivar UI_TOKENS_MAX: Максимальное значение слайдера токенов (Observer, Interviewer).
    :ivar UI_TOKENS_STEP: Шаг слайдера токенов (Observer, Interviewer).
    :ivar UI_EVAL_TOKENS_MIN: Минимальное значение слайдера токенов Evaluator.
    :ivar UI_EVAL_TOKENS_MAX: Максимальное значение слайдера токенов Evaluator.
    :ivar UI_EVAL_TOKENS_STEP: Шаг слайдера токенов Evaluator.
    :ivar UI_MAX_TURNS_MIN: Минимальное значение слайдера макс. ходов.
    :ivar UI_MAX_TURNS_MAX: Максимальное значение слайдера макс. ходов.
    :ivar UI_MAX_TURNS_STEP: Шаг слайдера макс. ходов.
    :ivar UI_OBSERVER_DEFAULT_TEMP: Температура Observer по умолчанию в UI.
    :ivar UI_OBSERVER_DEFAULT_TOKENS: Макс. токенов Observer по умолчанию в UI.
    :ivar UI_INTERVIEWER_DEFAULT_TEMP: Температура Interviewer по умолчанию в UI.
    :ivar UI_INTERVIEWER_DEFAULT_TOKENS: Макс. токенов Interviewer по умолчанию в UI.
    :ivar UI_EVALUATOR_DEFAULT_TEMP: Температура Evaluator по умолчанию в UI.
    :ivar UI_EVALUATOR_DEFAULT_TOKENS: Макс. токенов Evaluator по умолчанию в UI.
    """

    # ── Компоновка ────────────────────────────────────────────────────
    UI_CHAT_HEIGHT: int = 560
    UI_MSG_INPUT_LINES: int = 2
    UI_MSG_INPUT_MAX_LINES: int = 6
    UI_JOB_DESC_LINES: int = 6
    UI_JOB_DESC_MAX_LINES: int = 15
    UI_FEEDBACK_LINES: int = 25
    UI_FEEDBACK_MAX_LINES: int = 50

    # ── Слайдер температуры ───────────────────────────────────────────
    UI_TEMPERATURE_MIN: float = 0.0
    UI_TEMPERATURE_MAX: float = 1.5
    UI_TEMPERATURE_STEP: float = 0.05

    # ── Слайдер токенов (Observer, Interviewer) ───────────────────────
    UI_TOKENS_MIN: int = 256
    UI_TOKENS_MAX: int = 8192
    UI_TOKENS_STEP: int = 64

    # ── Слайдер токенов (Evaluator) ──────────────────────────────────
    UI_EVAL_TOKENS_MIN: int = 512
    UI_EVAL_TOKENS_MAX: int = 8192
    UI_EVAL_TOKENS_STEP: int = 128

    # ── Слайдер макс. ходов ──────────────────────────────────────────
    UI_MAX_TURNS_MIN: int = 5
    UI_MAX_TURNS_MAX: int = 50
    UI_MAX_TURNS_STEP: int = 1

    # ── Значения агентов по умолчанию ────────────────────────────────
    UI_OBSERVER_DEFAULT_TEMP: float = 0.3
    UI_OBSERVER_DEFAULT_TOKENS: int = 4000
    UI_INTERVIEWER_DEFAULT_TEMP: float = 0.7
    UI_INTERVIEWER_DEFAULT_TOKENS: int = 2000
    UI_EVALUATOR_DEFAULT_TEMP: float = 0.3
    UI_EVALUATOR_DEFAULT_TOKENS: int = 8000

    @field_validator("UI_CHAT_HEIGHT")
    @classmethod
    def _chat_height_positive(cls, v: int) -> int:
        """Проверяет, что высота чата положительна."""
        if v < 100:
            raise ValueError("UI_CHAT_HEIGHT must be >= 100")
        return v

    @field_validator("UI_TEMPERATURE_MAX")
    @classmethod
    def _temperature_max_positive(cls, v: float) -> float:
        """Проверяет, что максимальная температура положительна."""
        if v <= 0:
            raise ValueError("UI_TEMPERATURE_MAX must be > 0")
        return v

    @field_validator("UI_TEMPERATURE_STEP")
    @classmethod
    def _temperature_step_positive(cls, v: float) -> float:
        """Проверяет, что шаг температуры положителен."""
        if v <= 0:
            raise ValueError("UI_TEMPERATURE_STEP must be > 0")
        return v

    @field_validator(
        "UI_TOKENS_MIN",
        "UI_TOKENS_MAX",
        "UI_EVAL_TOKENS_MIN",
        "UI_EVAL_TOKENS_MAX",
    )
    @classmethod
    def _tokens_bounds_positive(cls, v: int) -> int:
        """Проверяет, что границы токенов положительны."""
        if v < 1:
            raise ValueError("Token bounds must be >= 1")
        return v

    @field_validator("UI_TOKENS_STEP", "UI_EVAL_TOKENS_STEP")
    @classmethod
    def _tokens_step_positive(cls, v: int) -> int:
        """Проверяет, что шаг токенов положителен."""
        if v < 1:
            raise ValueError("Token step must be >= 1")
        return v

    @field_validator("UI_MAX_TURNS_MIN")
    @classmethod
    def _max_turns_min_positive(cls, v: int) -> int:
        """Проверяет, что минимум ходов положителен."""
        if v < 1:
            raise ValueError("UI_MAX_TURNS_MIN must be >= 1")
        return v

    @field_validator("UI_MAX_TURNS_STEP")
    @classmethod
    def _max_turns_step_positive(cls, v: int) -> int:
        """Проверяет, что шаг ходов положителен."""
        if v < 1:
            raise ValueError("UI_MAX_TURNS_STEP must be >= 1")
        return v

    @model_validator(mode="after")
    def _validate_slider_ranges(self) -> GradioUISettings:
        """Проверяет, что минимальные значения слайдеров меньше максимальных."""
        if self.UI_TOKENS_MIN >= self.UI_TOKENS_MAX:
            raise ValueError(
                f"UI_TOKENS_MIN ({self.UI_TOKENS_MIN}) must be < UI_TOKENS_MAX ({self.UI_TOKENS_MAX})"
            )
        if self.UI_EVAL_TOKENS_MIN >= self.UI_EVAL_TOKENS_MAX:
            raise ValueError(
                f"UI_EVAL_TOKENS_MIN ({self.UI_EVAL_TOKENS_MIN}) must be < UI_EVAL_TOKENS_MAX ({self.UI_EVAL_TOKENS_MAX})"
            )
        if self.UI_MAX_TURNS_MIN >= self.UI_MAX_TURNS_MAX:
            raise ValueError(
                f"UI_MAX_TURNS_MIN ({self.UI_MAX_TURNS_MIN}) must be < UI_MAX_TURNS_MAX ({self.UI_MAX_TURNS_MAX})"
            )
        if self.UI_TEMPERATURE_MIN >= self.UI_TEMPERATURE_MAX:
            raise ValueError(
                f"UI_TEMPERATURE_MIN ({self.UI_TEMPERATURE_MIN}) must be < UI_TEMPERATURE_MAX ({self.UI_TEMPERATURE_MAX})"
            )
        return self


class Settings(
    AppSettings,
    EnvironmentSettings,
    RedisCacheSettings,
    ClientSideCacheSettings,
    LogSettings,
    LiteLLMSettings,
    InterviewSettings,
    LangfuseSettings,
    LLMCacheSettings,
    GradioUISettings,
):
    """Итоговые настройки приложения, собранные из всех тематических классов."""

    def ensure_directories(self) -> None:
        """Создаёт необходимые директории файловой системы."""
        self.APP_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.INTERVIEW_LOG_DIR.mkdir(parents=True, exist_ok=True)


_settings_lock: threading.Lock = threading.Lock()
_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """
    Возвращает singleton экземпляр настроек приложения.

    Lazy initialization: экземпляр создаётся при первом вызове.
    Потокобезопасен.

    :return: Экземпляр Settings.
    """
    global _settings_instance
    if _settings_instance is not None:
        return _settings_instance
    with _settings_lock:
        if _settings_instance is None:
            _settings_instance = Settings()
    return _settings_instance


def reset_settings() -> None:
    """Сбрасывает singleton настроек (используется в тестах)."""
    global _settings_instance
    with _settings_lock:
        _settings_instance = None


if TYPE_CHECKING:
    settings: Settings


def __getattr__(name: str) -> object:
    if name == "settings":
        return get_settings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
