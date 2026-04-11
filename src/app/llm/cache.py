"""
Модуль кэширования ответов LLM.

Предоставляет абстракцию кэширования через Protocol и реализацию
на базе Redis с lazy-подключением и graceful degradation.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
import traceback
from typing import Protocol, runtime_checkable

import redis.asyncio as aioredis

from ..core.logger_setup import get_system_logger
from ..utils.url import mask_url

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)

_CACHE_KEY_PREFIX: str = "llm_cache:"
_CONNECTION_RETRY_INTERVAL: float = 30.0


@runtime_checkable
class LLMCacheBackend(Protocol):
    """
    Протокол бэкенда кэширования LLM-ответов.

    Определяет интерфейс для чтения и записи кэшированных ответов.
    Реализации должны обеспечивать graceful degradation при недоступности хранилища.
    """

    async def get(self, key: str) -> str | None:
        """
        Получает кэшированный ответ по ключу.

        :param key: Ключ кэша (SHA-256 хеш параметров запроса).
        :return: Кэшированный ответ или None при промахе / ошибке.
        """
        ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """
        Сохраняет ответ в кэш.

        :param key: Ключ кэша.
        :param value: Ответ LLM для кэширования.
        :param ttl_seconds: Время жизни записи в секундах.
        """
        ...

    async def close(self) -> None:
        """Освобождает ресурсы бэкенда."""
        ...


class RedisLLMCache:
    """
    Реализация кэша LLM-ответов на базе Redis.

    Использует lazy-подключение: соединение создаётся при первом обращении.
    При недоступности Redis операции завершаются без ошибок (graceful degradation).
    После сбоя подключения повторная попытка выполняется через
    ``_CONNECTION_RETRY_INTERVAL`` секунд.

    :param redis_url: URL подключения к Redis.
    :param key_prefix: Префикс для ключей кэша.
    """

    def __init__(self, redis_url: str, key_prefix: str = _CACHE_KEY_PREFIX) -> None:
        self._redis_url: str = redis_url
        self._masked_url: str = mask_url(redis_url)
        self._key_prefix: str = key_prefix
        self._client: aioredis.Redis | None = None
        self._last_connection_failure: float = 0.0

    def _can_retry_connection(self) -> bool:
        """
        Проверяет, прошло ли достаточно времени для повторной попытки подключения.

        :return: True, если можно повторить попытку.
        """
        if self._last_connection_failure == 0.0:
            return True
        elapsed: float = time.monotonic() - self._last_connection_failure
        return elapsed >= _CONNECTION_RETRY_INTERVAL

    async def _ensure_client(self) -> aioredis.Redis | None:
        """
        Возвращает Redis-клиент, создавая его при необходимости.

        При ошибке подключения записывает время сбоя и возвращает None.
        Повторная попытка подключения выполняется не раньше чем через
        ``_CONNECTION_RETRY_INTERVAL`` секунд после последнего сбоя.

        :return: Клиент Redis или None при недоступности.
        """
        if self._client is not None:
            return self._client

        if not self._can_retry_connection():
            return None

        client: aioredis.Redis | None = None
        try:
            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await client.ping()
            self._client = client
            self._last_connection_failure = 0.0
            logger.info(f"LLM cache connected to Redis at {self._masked_url}")
            return self._client
        except Exception:
            tb: str = traceback.format_exc().replace("\n", " | ")
            logger.warning(f"LLM cache Redis connection failed: {tb}")
            self._last_connection_failure = time.monotonic()
            self._client = None
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.aclose()
            return None

    async def get(self, key: str) -> str | None:
        """
        Получает кэшированный ответ из Redis.

        :param key: Ключ кэша.
        :return: Кэшированный ответ или None.
        """
        client: aioredis.Redis | None = await self._ensure_client()
        if client is None:
            return None
        try:
            result: str | None = await client.get(f"{self._key_prefix}{key}")
            if result is not None:
                logger.debug(f"LLM cache hit for key={key[:16]}...")
            return result
        except Exception:
            tb: str = traceback.format_exc().replace("\n", " | ")
            logger.warning(f"LLM cache read error: {tb}")
            return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """
        Сохраняет ответ в Redis с TTL.

        :param key: Ключ кэша.
        :param value: Ответ для кэширования.
        :param ttl_seconds: Время жизни записи в секундах.
        """
        if ttl_seconds < 1:
            logger.warning(
                f"LLM cache set skipped: invalid ttl_seconds={ttl_seconds} (must be >= 1)"
            )
            return

        client: aioredis.Redis | None = await self._ensure_client()
        if client is None:
            return
        try:
            await client.setex(
                name=f"{self._key_prefix}{key}",
                time=ttl_seconds,
                value=value,
            )
            logger.debug(f"LLM cache stored key={key[:16]}..., ttl={ttl_seconds}s")
        except Exception:
            tb: str = traceback.format_exc().replace("\n", " | ")
            logger.warning(f"LLM cache write error: {tb}")

    async def close(self) -> None:
        """Закрывает соединение с Redis и сбрасывает состояние подключения."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                tb: str = traceback.format_exc().replace("\n", " | ")
                logger.warning(f"LLM cache close error: {tb}")
            finally:
                self._client = None
        self._last_connection_failure = 0.0
        logger.debug("LLM cache connection closed")


class NullLLMCache:
    """
    No-op реализация кэша LLM-ответов.

    Используется когда кэширование отключено в конфигурации.
    Все операции являются заглушками и не выполняют реальных действий.
    """

    async def get(self, key: str) -> str | None:  # noqa: ARG002
        """
        Всегда возвращает None (кэширование отключено).

        :param key: Ключ кэша (игнорируется).
        :return: None.
        """
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:  # noqa: ARG002
        """
        Ничего не делает (кэширование отключено).

        :param key: Ключ кэша (игнорируется).
        :param value: Значение (игнорируется).
        :param ttl_seconds: TTL (игнорируется).
        """

    async def close(self) -> None:
        """Ничего не делает (кэширование отключено)."""


def compute_cache_key(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    json_mode: bool,
) -> str:
    """
    Вычисляет детерминированный ключ кэша на основе параметров LLM-запроса.

    Ключ формируется как SHA-256 хеш JSON-представления параметров
    с сортировкой ключей для детерминированности. Параметр ``json_mode``
    включён в ключ, так как наличие ``response_format`` в запросе
    изменяет формат ответа LLM.

    :param model: Имя модели.
    :param messages: Список сообщений (system/user/assistant).
    :param temperature: Температура генерации.
    :param max_tokens: Максимальное число токенов.
    :param json_mode: Режим JSON-ответа (влияет на response_format).
    :return: SHA-256 хеш в hex-формате.
    """
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": round(temperature, 6),
        "max_tokens": max_tokens,
        "json_mode": json_mode,
    }
    serialized: str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def create_llm_cache(
    enabled: bool,
    redis_url: str,
) -> LLMCacheBackend:
    """
    Фабрика для создания бэкенда кэширования LLM-ответов.

    Возвращает ``RedisLLMCache`` если кэширование включено,
    иначе ``NullLLMCache`` (no-op).

    :param enabled: Флаг включения кэширования.
    :param redis_url: URL подключения к Redis.
    :return: Экземпляр бэкенда кэширования.
    """
    if not enabled:
        logger.info("LLM response cache is disabled")
        return NullLLMCache()

    masked_url: str = mask_url(redis_url)
    logger.info(f"LLM response cache enabled, Redis URL={masked_url}")
    return RedisLLMCache(redis_url=redis_url)
