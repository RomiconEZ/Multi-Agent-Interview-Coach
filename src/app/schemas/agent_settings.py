"""
Схемы настроек агентов и конфигурации интервью.

Определяет структуры для пользовательской настройки параметров
каждого агента и общей конфигурации сессии интервью.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SingleAgentConfig(BaseModel):
    """
    Конфигурация одного агента.

    :ivar temperature: Температура генерации LLM (0.0 — детерминированный, 2.0 — максимально креативный).
    :ivar max_tokens: Максимальное количество токенов в ответе LLM.
    :ivar generation_retries: Количество повторных попыток генерации при ошибке парсинга ответа LLM.
    """

    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(ge=64, le=8192)
    generation_retries: int = Field(ge=0, le=10)

    @field_validator("temperature")
    @classmethod
    def round_temperature(cls, v: float) -> float:
        """Округляет температуру до двух знаков после запятой."""
        return round(v, 2)


class AgentSettings(BaseModel):
    """
    Настройки всех агентов системы.

    :ivar observer: Конфигурация агента-наблюдателя.
    :ivar interviewer: Конфигурация агента-интервьюера.
    :ivar evaluator: Конфигурация агента-оценщика.
    """

    observer: SingleAgentConfig = Field(
        default_factory=lambda: SingleAgentConfig(
            temperature=0.3, max_tokens=1000, generation_retries=2,
        ),
    )
    interviewer: SingleAgentConfig = Field(
        default_factory=lambda: SingleAgentConfig(
            temperature=0.7, max_tokens=800, generation_retries=0,
        ),
    )
    evaluator: SingleAgentConfig = Field(
        default_factory=lambda: SingleAgentConfig(
            temperature=0.3, max_tokens=3000, generation_retries=2,
        ),
    )


class InterviewConfig(BaseModel):
    """
    Полная конфигурация сессии интервью.

    :ivar model: Имя модели LLM.
    :ivar max_turns: Максимальное количество ходов интервью.
    :ivar job_description: Описание вакансии (опционально).
    :ivar agent_settings: Настройки агентов.
    """

    model: str | None = None
    max_turns: int = Field(ge=1, le=100)
    job_description: str | None = None
    agent_settings: AgentSettings = Field(default_factory=AgentSettings)

    @field_validator("job_description", mode="before")
    @classmethod
    def strip_job_description(cls, v: str | None) -> str | None:
        """Очищает пустые строки описания вакансии."""
        if v is None:
            return None
        stripped: str = v.strip()
        return stripped if stripped else None

    @field_validator("model", mode="before")
    @classmethod
    def strip_model(cls, v: str | None) -> str | None:
        """Очищает пустые строки имени модели."""
        if v is None:
            return None
        stripped: str = v.strip()
        return stripped if stripped else None