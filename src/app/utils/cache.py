"""
Модуль кэширования с использованием Redis.

Предоставляет управление подключением к Redis.
"""

from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis

from ..core.exceptions.cache_exceptions import MissingClientError

_pool: ConnectionPool | None = None
_client: Redis | None = None


def set_redis_connection(pool: ConnectionPool, client: Redis) -> None:
    """
    Устанавливает подключение к Redis.

    :param pool: Пул соединений Redis.
    :param client: Клиент Redis.
    :raises ValueError: Если pool или client равны None.
    """
    global _pool, _client
    if pool is None:
        raise ValueError("pool cannot be None")
    if client is None:
        raise ValueError("client cannot be None")
    _pool = pool
    _client = client


def clear_redis_connection() -> None:
    """Очищает ссылки на подключение к Redis."""
    global _pool, _client
    _pool = None
    _client = None


def get_redis_client() -> Redis:
    """
    Возвращает активный клиент Redis.

    :return: Клиент Redis.
    :raises MissingClientError: Если клиент не инициализирован.
    """
    if _client is None:
        raise MissingClientError()
    return _client


def get_redis_pool() -> ConnectionPool | None:
    """
    Возвращает пул соединений Redis.

    :return: Пул соединений или None.
    """
    return _pool


def is_redis_connected() -> bool:
    """
    Проверяет, инициализировано ли подключение к Redis.

    :return: True, если клиент инициализирован.
    """
    return _client is not None
