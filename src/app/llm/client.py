"""
Клиент для взаимодействия с LiteLLM API.

Предоставляет унифицированный интерфейс для работы с различными LLM через LiteLLM прокси.
Включает механизмы защиты: circuit breaker, health check, retry с exponential backoff.
Поддерживает кэширование ответов и алертинг при критических сбоях.
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
from ..observability.alerts import get_alert_manager
from .cache import LLMCacheBackend, compute_cache_key, create_llm_cache
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpen

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)

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
    :ivar retry_backoff_base: Базовая задержка для экспоненциального backoff (секунды).
    :ivar retry_backoff_max: Максимальная задержка для экспоненциального backoff (секунды).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout: int,
        max_retries: int,
        retry_backoff_base: float,
        retry_backoff_max: float,
        health_check_timeout: float,
        circuit_breaker: CircuitBreaker,
        cache: LLMCacheBackend,
        cache_ttl_seconds: int,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._retry_backoff_base = retry_backoff_base
        self._retry_backoff_max = retry_backoff_max
        self._health_check_timeout = health_check_timeout
        self._circuit_breaker = circuit_breaker
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds
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

    async def check_health(self) -> bool:
        """
        Проверяет доступность LLM API.

        Выполняет запрос к эндпоинту ``/health/readiness`` LiteLLM proxy.
        Проверяет готовность прокси принимать запросы (включая соединение с БД),
        без выполнения реальных LLM-вызовов.

        :return: True если API доступен, False иначе.
        """
        try:
            client: httpx.AsyncClient = await self._get_client()
            response: httpx.Response = await client.get(
                "/health/readiness",
                timeout=httpx.Timeout(self._health_check_timeout),
            )
            is_healthy: bool = response.status_code == 200
            if is_healthy:
                logger.info(f"LLM API readiness check passed: {self._base_url}")
            else:
                logger.warning(
                    f"LLM API readiness check failed: status={response.status_code}"
                )
                alert_mgr = get_alert_manager()
                await alert_mgr.fire_warning(
                    source="LLMClient.check_health",
                    message=f"LLM API readiness check failed: status={response.status_code}",
                    metadata={"base_url": self._base_url},
                )
            return is_healthy
        except httpx.TimeoutException:
            logger.warning(
                f"LLM API readiness check timed out after {self._health_check_timeout}s"
            )
            alert_mgr = get_alert_manager()
            await alert_mgr.fire_warning(
                source="LLMClient.check_health",
                message=f"LLM API readiness check timed out after {self._health_check_timeout}s",
                metadata={"base_url": self._base_url},
            )
            return False
        except httpx.RequestError as e:
            logger.warning(f"LLM API readiness check failed: {e}")
            alert_mgr = get_alert_manager()
            await alert_mgr.fire_warning(
                source="LLMClient.check_health",
                message=f"LLM API readiness check request error: {e}",
                metadata={"base_url": self._base_url},
            )
            return False

    async def close(self) -> None:
        """Закрывает HTTP клиент и кэш."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
        await self._cache.close()

    def _compute_retry_delay(self, attempt: int) -> float:
        """
        Вычисляет задержку перед повторной попыткой с экспоненциальным backoff.

        :param attempt: Номер текущей попытки (0-based).
        :return: Задержка в секундах.
        """
        return min(
            self._retry_backoff_base * (2**attempt),
            self._retry_backoff_max,
        )

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

    @staticmethod
    def _extract_response_cost(response: httpx.Response) -> float:
        """
        Извлекает стоимость запроса из ответа LiteLLM proxy.

        LiteLLM proxy при включённом трекинге расходов возвращает
        стоимость вызова в заголовке ``x-litellm-response-cost``.
        Для локальных моделей без настроенного прайсинга стоимость
        будет равна 0.0.

        :param response: HTTP-ответ от LiteLLM proxy.
        :return: Стоимость вызова в USD (0.0 если данные недоступны).
        """
        cost_header: str | None = response.headers.get("x-litellm-response-cost")
        if cost_header is not None:
            try:
                return float(cost_header)
            except (ValueError, TypeError):
                logger.debug(f"Failed to parse cost header: {cost_header}")
        return 0.0

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

        Перед обращением к LLM проверяет кэш. При cache hit возвращает
        кэшированный ответ без обращения к сети. При cache miss выполняет
        обычный запрос и сохраняет результат в кэш.

        :param messages: Список сообщений.
        :param temperature: Температура генерации.
        :param max_tokens: Максимальное число токенов.
        :param generation_name: Имя генерации для Langfuse.
        :param json_mode: Запрос JSON-формата ответа через response_format.
        :return: Ответ модели.
        :raises LLMClientError: При ошибке запроса или срабатывании circuit breaker.
        """
        # ── Проверка кэша ────────────────────────────────────────────────
        cache_key: str = compute_cache_key(
            self._model,
            messages,
            temperature,
            max_tokens,
            json_mode,
        )
        cached_response: str | None = await self._cache.get(cache_key)
        if cached_response is not None:
            logger.info(
                f"LLM cache hit for {generation_name}, "
                f"model={self._model}, key={cache_key[:16]}..."
            )
            generation = self._langfuse.create_generation(
                trace=self._current_trace,
                name=generation_name,
                model=self._model,
                input_messages=messages,
                metadata={
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "json_mode": json_mode,
                    "cached": True,
                },
            )
            self._langfuse.end_generation(
                generation=generation,
                output=cached_response,
                cost_usd=0.0,
                usage={"input": 0, "output": 0, "total": 0},
                session_id=self._session_id,
                generation_name=generation_name,
            )
            return cached_response

        # ── Обычный LLM-вызов ────────────────────────────────────────────
        client = await self._get_client()

        # Проверяем circuit breaker перед выполнением запроса
        try:
            self._circuit_breaker.check()
        except CircuitBreakerOpen as e:
            alert_mgr = get_alert_manager()
            await alert_mgr.fire_critical(
                source="LLMClient",
                message=f"Circuit breaker is OPEN, request rejected: {e}",
                metadata={"model": self._model, "generation": generation_name},
            )
            raise LLMClientError(str(e)) from e

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

                # Извлекаем стоимость из заголовков LiteLLM proxy
                response_cost: float = self._extract_response_cost(response)

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
                    cost_usd=response_cost,
                    usage=usage_dict,
                    session_id=self._session_id,
                    generation_name=generation_name,
                )

                # Успешный запрос — сбрасываем circuit breaker
                self._circuit_breaker.record_success()

                logger.debug(
                    f"LLM response received, length={len(content)}, "
                    f"usage={usage_dict}, cost=${response_cost:.6f}"
                )

                # ── Сохранение в кэш ─────────────────────────────────────
                await self._cache.set(
                    cache_key,
                    content,
                    self._cache_ttl_seconds,
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

                # Не-retryable HTTP ошибки (4xx кроме 429) —
                # не влияют на circuit breaker (это ошибки клиента, не сервиса)
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

        # Все retry исчерпаны — фиксируем сбой в circuit breaker
        self._circuit_breaker.record_failure()

        error_msg: str = (
            f"Max retries ({self._max_retries}) exceeded, last error: {last_error}"
        )
        self._langfuse.end_generation_with_error(
            generation=generation,
            error=error_msg,
        )

        # Алерт о полном исчерпании retry
        alert_mgr = get_alert_manager()
        await alert_mgr.fire_warning(
            source="LLMClient",
            message=f"All retries exhausted for {generation_name}: {error_msg}",
            metadata={
                "model": self._model,
                "generation": generation_name,
                "max_retries": self._max_retries,
                "circuit_breaker_failures": self._circuit_breaker.failure_count,
            },
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


_shared_circuit_breaker: CircuitBreaker | None = None


def _get_shared_circuit_breaker() -> CircuitBreaker:
    """
    Возвращает разделяемый экземпляр circuit breaker.

    Используется всеми LLM-клиентами для отслеживания доступности
    общего LiteLLM proxy. Singleton гарантирует, что состояние
    circuit breaker сохраняется между сессиями.

    :return: Экземпляр CircuitBreaker.
    """
    global _shared_circuit_breaker
    if _shared_circuit_breaker is None:
        _shared_circuit_breaker = CircuitBreaker(
            failure_threshold=settings.LITELLM_CIRCUIT_BREAKER_THRESHOLD,
            recovery_timeout=settings.LITELLM_CIRCUIT_BREAKER_RECOVERY,
        )
    return _shared_circuit_breaker


_shared_cache: LLMCacheBackend | None = None


def _get_shared_cache() -> LLMCacheBackend:
    """
    Возвращает разделяемый экземпляр кэша LLM-ответов.

    Singleton гарантирует единое подключение к Redis для всех
    ``LLMClient`` экземпляров в процессе.

    :return: Экземпляр LLMCacheBackend.
    """
    global _shared_cache
    if _shared_cache is None:
        _shared_cache = create_llm_cache(
            enabled=settings.LLM_CACHE_ENABLED,
            redis_url=settings.REDIS_CACHE_URL,
        )
    return _shared_cache


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
        retry_backoff_base=settings.LITELLM_RETRY_BACKOFF_BASE,
        retry_backoff_max=settings.LITELLM_RETRY_BACKOFF_MAX,
        health_check_timeout=settings.LITELLM_HEALTH_CHECK_TIMEOUT,
        circuit_breaker=_get_shared_circuit_breaker(),
        cache=_get_shared_cache(),
        cache_ttl_seconds=settings.LLM_CACHE_TTL_SECONDS,
    )
