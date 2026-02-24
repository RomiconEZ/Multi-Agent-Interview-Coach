"""
Клиент для взаимодействия с LiteLLM API.

Предоставляет унифицированный интерфейс для работы с различными LLM через LiteLLM прокси.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from langfuse.client import StatefulTraceClient

from ..core.config import settings
from ..core.logger_setup import get_system_logger
from ..observability import get_langfuse_tracker

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)

_RETRY_BACKOFF_BASE: float = 0.5
_RETRY_BACKOFF_MAX: float = 30.0
_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


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
        self._langfuse = get_langfuse_tracker()
        self._current_trace: StatefulTraceClient | None = None
        self._session_id: str | None = None
        self._json_mode_supported: bool = True

    @property
    def model(self) -> str:
        """Возвращает имя модели."""
        return self._model

    def set_trace(
        self,
        trace: StatefulTraceClient | None,
        session_id: str | None,
    ) -> None:
        """
        Устанавливает текущий трейс для LLM вызовов.

        :param trace: Трейс Langfuse.
        :param session_id: ID сессии для метрик.
        """
        self._current_trace = trace
        self._session_id = session_id

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Возвращает HTTP клиент, создавая его при необходимости.

        :return: Активный HTTP клиент.
        :raises LLMClientError: Если API ключ не задан.
        """
        if self._client is None or self._client.is_closed:
            if not self._api_key:
                raise LLMClientError(
                    "LITELLM_API_KEY is not set. Please set it in .env file."
                )
            headers: dict[str, str] = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }
            logger.debug(
                f"Creating LLM client for {self._base_url}, "
                f"key=***{self._api_key[-4:] if len(self._api_key) > 4 else '****'}"
            )
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

    @staticmethod
    def _compute_retry_delay(attempt: int) -> float:
        """
        Вычисляет задержку перед повторной попыткой с экспоненциальным backoff.

        :param attempt: Номер текущей попытки (0-based).
        :return: Задержка в секундах.
        """
        return min(_RETRY_BACKOFF_BASE * (2**attempt), _RETRY_BACKOFF_MAX)

    @staticmethod
    def _is_json_mode_unsupported_error(error_text: str) -> bool:
        """
        Проверяет, связана ли ошибка HTTP 400 с неподдерживаемым response_format.

        :param error_text: Тело ответа с ошибкой.
        :return: True если ошибка вызвана response_format.
        """
        lower: str = error_text.lower()
        return "response_format" in lower or (
            "json_object" in lower and ("400" in lower or "bad" in lower)
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        generation_name: str,
        json_mode: bool = False,
    ) -> str:
        """
        Выполняет запрос к LLM.

        :param messages: Список сообщений.
        :param temperature: Температура генерации.
        :param max_tokens: Максимальное число токенов.
        :param generation_name: Имя генерации для Langfuse.
        :param json_mode: Запрос JSON-формата ответа через response_format.
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

        if json_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": generation_name,
                    "schema": {"type": "object"},
                },
            }

        generation = self._langfuse.create_generation(
            trace=self._current_trace,
            name=generation_name,
            model=self._model,
            input_messages=messages,
            metadata={
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            },
        )

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                logger.debug(
                    f"LLM request attempt {attempt + 1}/{self._max_retries + 1}, "
                    f"model={self._model}, json_mode={json_mode}"
                )
                response = await client.post("/v1/chat/completions", json=payload)
                response.raise_for_status()

                data = response.json()
                content: str = data["choices"][0]["message"]["content"]

                usage = data.get("usage")
                usage_dict: dict[str, int] | None = None
                if usage:
                    usage_dict = {
                        "input": usage.get("prompt_tokens", 0),
                        "output": usage.get("completion_tokens", 0),
                        "total": usage.get("total_tokens", 0),
                    }

                self._langfuse.end_generation(
                    generation=generation,
                    output=content,
                    usage=usage_dict,
                    session_id=self._session_id,
                    generation_name=generation_name,
                )

                logger.debug(
                    f"LLM response received, length={len(content)}, usage={usage_dict}"
                )
                return content

            except httpx.HTTPStatusError as e:
                last_error = e
                status_code: int = e.response.status_code
                response_body: str = e.response.text[:500]
                logger.warning(
                    f"HTTP error on attempt {attempt + 1}: "
                    f"status={status_code}, body={response_body}"
                )

                if status_code in _RETRYABLE_HTTP_CODES:
                    if attempt < self._max_retries:
                        delay: float = self._compute_retry_delay(attempt)
                        logger.info(f"Retrying in {delay:.1f}s (status={status_code})")
                        await asyncio.sleep(delay)
                    continue

                self._langfuse.end_generation_with_error(
                    generation=generation,
                    error=f"HTTP error {status_code}: {response_body}",
                )
                raise LLMClientError(
                    f"HTTP error {status_code}: {response_body}"
                ) from e

            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(
                    f"Timeout on attempt {attempt + 1}/{self._max_retries + 1}"
                )
                if attempt < self._max_retries:
                    delay = self._compute_retry_delay(attempt)
                    await asyncio.sleep(delay)
                continue

            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    f"Request error on attempt {attempt + 1}/{self._max_retries + 1}: {e}"
                )
                if attempt < self._max_retries:
                    delay = self._compute_retry_delay(attempt)
                    await asyncio.sleep(delay)
                continue

            except (KeyError, json.JSONDecodeError) as e:
                self._langfuse.end_generation_with_error(
                    generation=generation,
                    error=f"Invalid response format: {e}",
                )
                raise LLMClientError(f"Invalid response format: {e}") from e

        error_msg: str = (
            f"Max retries ({self._max_retries}) exceeded, last error: {last_error}"
        )
        self._langfuse.end_generation_with_error(
            generation=generation,
            error=error_msg,
        )
        raise LLMClientError(error_msg)

    @staticmethod
    def _extract_json_from_text(text: str) -> dict[str, Any]:
        """
        Извлекает JSON-объект из текстового ответа LLM.

        Обрабатывает типичные обёртки: markdown code blocks, текст вокруг JSON.

        :param text: Текстовый ответ LLM.
        :return: Распарсенный JSON-объект.
        :raises LLMClientError: Если JSON не найден или невалиден.
        """
        cleaned: str = text.strip()

        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        start: int = cleaned.find("{")
        end: int = cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass

        raise LLMClientError(
            f"No valid JSON found in LLM response (length={len(text)}): {text[:300]}"
        )

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        generation_name: str,
    ) -> dict[str, Any]:
        """
        Выполняет запрос к LLM с ожиданием JSON ответа.

        Использует ``response_format`` для принудительного JSON-вывода
        когда модель поддерживает эту возможность. Если модель не поддерживает
        ``response_format`` (ошибка HTTP 400), автоматически переключается
        на текстовый режим и извлекает JSON из ответа.

        Состояние поддержки кешируется: после первой ошибки все последующие
        вызовы сразу используют текстовый режим без лишних запросов.

        :param messages: Список сообщений.
        :param temperature: Температура генерации.
        :param max_tokens: Максимальное число токенов.
        :param generation_name: Имя генерации для Langfuse.
        :return: Распарсенный JSON ответ.
        :raises LLMClientError: При ошибке запроса или парсинга.
        """
        if self._json_mode_supported:
            try:
                response: str = await self.complete(
                    messages,
                    temperature,
                    max_tokens,
                    generation_name=generation_name,
                    json_mode=True,
                )
                return self._extract_json_from_text(response)
            except LLMClientError as e:
                if self._is_json_mode_unsupported_error(str(e)):
                    self._json_mode_supported = False
                    logger.warning(
                        f"JSON mode (response_format) not supported by model "
                        f"{self._model}, falling back to text mode for all subsequent calls"
                    )
                else:
                    raise

        response = await self.complete(
            messages,
            temperature,
            max_tokens,
            generation_name=generation_name,
            json_mode=False,
        )
        return self._extract_json_from_text(response)


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
