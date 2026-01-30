"""
Клиент для взаимодействия с LiteLLM API.

Предоставляет унифицированный интерфейс для работы с различными LLM через LiteLLM прокси.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..core.config import settings
from ..core.logger_setup import get_system_logger

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


class LLMClientError(Exception):
    """Ошибка клиента LLM."""

    pass


class LLMClient:
    """
    Клиент для взаимодействия с LiteLLM.

    :ivar base_url: Базовый URL LiteLLM API.
    :ivar model: Имя модели.
    :ivar timeout: Таймаут запросов.
    :ivar max_retries: Максимальное число повторных попыток.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout: int,
        max_retries: int,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    @property
    def model(self) -> str:
        """Возвращает имя модели."""
        return self._model

    async def _get_client(self) -> httpx.AsyncClient:
        """Возвращает HTTP клиент."""
        if self._client is None or self._client.is_closed:
            if not self._api_key:
                raise LLMClientError(
                    "LITELLM_API_KEY is not set. Please set it in .env file."
                )
            headers: dict[str, str] = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }
            logger.debug(f"Creating LLM client for {self._base_url}, key=***{self._api_key[-4:] if len(self._api_key) > 4 else '****'}")
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def close(self) -> None:
        """Закрывает HTTP клиент."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """
        Выполняет запрос к LLM.

        :param messages: Список сообщений.
        :param temperature: Температура генерации.
        :param max_tokens: Максимальное число токенов.
        :return: Ответ модели.
        :raises LLMClientError: При ошибке запроса.
        """
        client = await self._get_client()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                logger.debug(f"LLM request attempt {attempt + 1}, model={self._model}")
                response = await client.post("/v1/chat/completions", json=payload)
                response.raise_for_status()

                data = response.json()
                content: str = data["choices"][0]["message"]["content"]
                logger.debug(f"LLM response received, length={len(content)}")
                return content

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(f"HTTP error on attempt {attempt + 1}: {e.response.status_code}")
                if e.response.status_code >= 500:
                    continue
                raise LLMClientError(f"HTTP error: {e.response.status_code}") from e

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"Timeout on attempt {attempt + 1}")
                continue

            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"Request error on attempt {attempt + 1}: {e}")
                continue

            except (KeyError, json.JSONDecodeError) as e:
                raise LLMClientError(f"Invalid response format: {e}") from e

        raise LLMClientError(f"Max retries exceeded: {last_error}")

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        """
        Выполняет запрос к LLM с ожиданием JSON ответа.

        :param messages: Список сообщений.
        :param temperature: Температура генерации.
        :param max_tokens: Максимальное число токенов.
        :return: Распарсенный JSON ответ.
        :raises LLMClientError: При ошибке запроса или парсинга.
        """
        response = await self.complete(messages, temperature, max_tokens)
        cleaned = response.strip()

        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {response[:200]}")
            raise LLMClientError(f"Invalid JSON in response: {e}") from e


def create_llm_client(model: str | None = None) -> LLMClient:
    """
    Создаёт экземпляр LLM клиента с настройками из конфигурации.

    :param model: Имя модели (по умолчанию из конфигурации).
    :return: Экземпляр LLMClient.
    """
    return LLMClient(
        base_url=settings.LITELLM_BASE_URL,
        model=model or settings.LITELLM_MODEL,
        api_key=settings.LITELLM_API_KEY,
        timeout=settings.LITELLM_TIMEOUT,
        max_retries=settings.LITELLM_MAX_RETRIES,
    )
