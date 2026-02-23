"""
Базовый класс для AI-агентов.

Определяет общий интерфейс и функциональность для всех агентов системы.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..llm.client import LLMClient
from ..schemas.agent_settings import SingleAgentConfig
from ..schemas.interview import InterviewState


class BaseAgent(ABC):
    """
    Абстрактный базовый класс агента.

    :ivar name: Имя агента.
    :ivar llm_client: Клиент LLM.
    :ivar config: Конфигурация агента (температура, макс. токенов).
    """

    def __init__(
        self,
        name: str,
        llm_client: LLMClient,
        config: SingleAgentConfig,
    ) -> None:
        self._name = name
        self._llm_client = llm_client
        self._config = config

    @property
    def name(self) -> str:
        """Возвращает имя агента."""
        return self._name

    @property
    def config(self) -> SingleAgentConfig:
        """Возвращает конфигурацию агента."""
        return self._config

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Возвращает системный промпт агента."""
        pass

    def _build_messages(
        self,
        user_content: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        """
        Строит список сообщений для LLM с правильным чередованием ролей.

        :param user_content: Текущее сообщение пользователя/системы.
        :param history: История сообщений.
        :return: Список сообщений для LLM.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]

        if history:
            filtered_history = list(history)

            if filtered_history and filtered_history[-1]["role"] == "user":
                filtered_history = filtered_history[:-1]

            if filtered_history and filtered_history[0]["role"] == "assistant":
                messages.append({"role": "user", "content": "Начнём интервью."})

            messages.extend(filtered_history)

        messages.append({"role": "user", "content": user_content})
        return messages

    @staticmethod
    def _build_job_description_block(job_description: str | None) -> str:
        """
        Формирует блок описания вакансии для включения в контекст агента.

        :param job_description: Текст описания вакансии или None.
        :return: Форматированный блок текста (пустая строка если описания нет).
        """
        if not job_description:
            return ""

        return (
            "\n## ОПИСАНИЕ ВАКАНСИИ\n"
            "Интервью проводится по конкретной вакансии. "
            "Адаптируй свою работу под требования этой вакансии.\n"
            "<job_description>\n"
            f"{job_description}\n"
            "</job_description>\n"
        )

    @abstractmethod
    async def process(self, state: InterviewState, **kwargs: Any) -> Any:
        """
        Обрабатывает текущее состояние.

        :param state: Состояние интервью.
        :param kwargs: Дополнительные параметры.
        :return: Результат обработки.
        """
        pass
