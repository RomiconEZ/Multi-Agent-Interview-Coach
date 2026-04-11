"""
Тесты для модуля кэширования LLM-ответов.

Покрывает: вычисление ключей, NullLLMCache, RedisLLMCache (мок),
фабрику create_llm_cache.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.app.llm.cache import (
    NullLLMCache,
    RedisLLMCache,
    compute_cache_key,
    create_llm_cache,
)


class TestComputeCacheKey:
    """Тесты вычисления детерминированного ключа кэша."""

    def test_deterministic_output(self) -> None:
        """Одинаковые входы дают одинаковый ключ."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
        key_a: str = compute_cache_key("model-a", messages, 0.3, 4096, False)
        key_b: str = compute_cache_key("model-a", messages, 0.3, 4096, False)
        assert key_a == key_b

    def test_different_model_different_key(self) -> None:
        """Разные модели дают разные ключи."""
        messages: list[dict[str, str]] = [{"role": "user", "content": "Hi"}]
        key_a: str = compute_cache_key("model-a", messages, 0.3, 4096, False)
        key_b: str = compute_cache_key("model-b", messages, 0.3, 4096, False)
        assert key_a != key_b

    def test_different_temperature_different_key(self) -> None:
        """Разные температуры дают разные ключи."""
        messages: list[dict[str, str]] = [{"role": "user", "content": "Hi"}]
        key_a: str = compute_cache_key("model-a", messages, 0.3, 4096, False)
        key_b: str = compute_cache_key("model-a", messages, 0.7, 4096, False)
        assert key_a != key_b

    def test_different_max_tokens_different_key(self) -> None:
        """Разные max_tokens дают разные ключи."""
        messages: list[dict[str, str]] = [{"role": "user", "content": "Hi"}]
        key_a: str = compute_cache_key("model-a", messages, 0.3, 4096, False)
        key_b: str = compute_cache_key("model-a", messages, 0.3, 2048, False)
        assert key_a != key_b

    def test_different_messages_different_key(self) -> None:
        """Разные сообщения дают разные ключи."""
        msg_a: list[dict[str, str]] = [{"role": "user", "content": "Hello"}]
        msg_b: list[dict[str, str]] = [{"role": "user", "content": "Goodbye"}]
        key_a: str = compute_cache_key("model-a", msg_a, 0.3, 4096, False)
        key_b: str = compute_cache_key("model-a", msg_b, 0.3, 4096, False)
        assert key_a != key_b

    def test_different_json_mode_different_key(self) -> None:
        """Разный json_mode даёт разные ключи."""
        messages: list[dict[str, str]] = [{"role": "user", "content": "Hi"}]
        key_a: str = compute_cache_key("model-a", messages, 0.3, 4096, False)
        key_b: str = compute_cache_key("model-a", messages, 0.3, 4096, True)
        assert key_a != key_b

    def test_key_is_hex_sha256(self) -> None:
        """Ключ является hex-строкой длиной 64 символа (SHA-256)."""
        messages: list[dict[str, str]] = [{"role": "user", "content": "test"}]
        key: str = compute_cache_key("model", messages, 0.5, 1024, False)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_message_order_matters(self) -> None:
        """Порядок сообщений влияет на ключ."""
        msg_a: list[dict[str, str]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
        ]
        msg_b: list[dict[str, str]] = [
            {"role": "user", "content": "usr"},
            {"role": "system", "content": "sys"},
        ]
        key_a: str = compute_cache_key("m", msg_a, 0.0, 100, False)
        key_b: str = compute_cache_key("m", msg_b, 0.0, 100, False)
        assert key_a != key_b

    def test_empty_messages(self) -> None:
        """Пустой список сообщений корректно хешируется."""
        key: str = compute_cache_key("model", [], 0.5, 100, False)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


class TestNullLLMCache:
    """Тесты no-op кэша."""

    async def test_get_returns_none(self) -> None:
        """``get`` всегда возвращает None."""
        cache = NullLLMCache()
        result: str | None = await cache.get("any-key")
        assert result is None

    async def test_set_does_not_raise(self) -> None:
        """``set`` не вызывает исключений."""
        cache = NullLLMCache()
        result = await cache.set("key", "value", 3600)
        assert result is None

    async def test_close_does_not_raise(self) -> None:
        """``close`` не вызывает исключений."""
        cache = NullLLMCache()
        await cache.close()


class TestRedisLLMCache:
    """Тесты Redis-кэша с мокированным клиентом."""

    async def test_get_cache_hit(self) -> None:
        """Возвращает значение при наличии ключа в Redis."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="cached_response")
        cache._client = mock_client

        result: str | None = await cache.get("test-key")
        assert result == "cached_response"
        mock_client.get.assert_awaited_once_with("llm_cache:test-key")

    async def test_get_cache_miss(self) -> None:
        """Возвращает None при отсутствии ключа в Redis."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        cache._client = mock_client

        result: str | None = await cache.get("missing-key")
        assert result is None

    async def test_set_stores_with_ttl(self) -> None:
        """``set`` вызывает ``setex`` с правильными параметрами."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")

        mock_client = AsyncMock()
        mock_client.setex = AsyncMock()
        cache._client = mock_client

        await cache.set("my-key", "my-value", 7200)

        mock_client.setex.assert_awaited_once_with(
            name="llm_cache:my-key",
            time=7200,
            value="my-value",
        )

    async def test_get_graceful_on_redis_error(self) -> None:
        """При ошибке Redis ``get`` возвращает None без исключения."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("redis down"))
        cache._client = mock_client

        result: str | None = await cache.get("key")
        assert result is None

    async def test_set_graceful_on_redis_error(self) -> None:
        """При ошибке Redis ``set`` завершается без исключения и возвращает None."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")

        mock_client = AsyncMock()
        mock_client.setex = AsyncMock(side_effect=ConnectionError("redis down"))
        cache._client = mock_client

        result = await cache.set("key", "value", 60)
        assert result is None

    async def test_connection_failed_flag_prevents_retries(self) -> None:
        """После сбоя подключения повторные попытки не выполняются."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")
        cache._connection_failed = True

        result: str | None = await cache.get("key")
        assert result is None

    async def test_ensure_client_sets_connection_failed_on_error(self) -> None:
        """``_ensure_client`` устанавливает ``_connection_failed`` при ошибке подключения."""
        cache = RedisLLMCache(redis_url="redis://bad-host:6379")
        assert cache._connection_failed is False

        with patch(
            "src.app.llm.cache.aioredis.from_url",
            side_effect=ConnectionRefusedError("connection refused"),
        ):
            client = await cache._ensure_client()

        assert client is None
        assert cache._connection_failed is True
        assert cache._client is None

        # Повторный вызов сразу возвращает None без попытки подключения
        client_again = await cache._ensure_client()
        assert client_again is None

    async def test_ensure_client_sets_failed_on_ping_error(self) -> None:
        """``_ensure_client`` устанавливает ``_connection_failed`` при ошибке ping."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("ping failed"))

        with patch(
            "src.app.llm.cache.aioredis.from_url",
            return_value=mock_redis,
        ):
            client = await cache._ensure_client()

        assert client is None
        assert cache._connection_failed is True

    async def test_close_calls_aclose(self) -> None:
        """``close`` вызывает ``aclose`` на клиенте Redis."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")

        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        cache._client = mock_client

        await cache.close()
        mock_client.aclose.assert_awaited_once()
        assert cache._client is None

    async def test_close_when_no_client(self) -> None:
        """``close`` безопасен при отсутствии клиента."""
        cache = RedisLLMCache(redis_url="redis://localhost:6379")
        await cache.close()

    async def test_custom_key_prefix(self) -> None:
        """Пользовательский префикс ключей работает корректно."""
        cache = RedisLLMCache(
            redis_url="redis://localhost:6379",
            key_prefix="custom:",
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value="val")
        cache._client = mock_client

        await cache.get("k")
        mock_client.get.assert_awaited_once_with("custom:k")


class TestCreateLlmCache:
    """Тесты фабрики создания кэша."""

    def test_disabled_returns_null_cache(self) -> None:
        """При ``enabled=False`` возвращается NullLLMCache."""
        result = create_llm_cache(enabled=False, redis_url="redis://localhost:6379")
        assert isinstance(result, NullLLMCache)

    def test_enabled_returns_redis_cache(self) -> None:
        """При ``enabled=True`` возвращается RedisLLMCache."""
        result = create_llm_cache(enabled=True, redis_url="redis://localhost:6379")
        assert isinstance(result, RedisLLMCache)
