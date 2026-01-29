"""
Модуль кэширования для FastAPI-эндпоинтов с использованием Redis.

Предоставляет декоратор для кэширования результатов эндпоинтов
и управление подключением к Redis.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Callable
from typing import Any

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from redis.asyncio import ConnectionPool, Redis

from ..core.exceptions.cache_exceptions import (
    CacheIdentificationInferenceError,
    InvalidRequestError,
    MissingClientError,
)

# ──────────────────────────────────────────────────────────────────────────────
# Внутреннее состояние модуля (приватные переменные)
# ──────────────────────────────────────────────────────────────────────────────
_pool: ConnectionPool | None = None
_client: Redis | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Управление подключением к Redis
# ──────────────────────────────────────────────────────────────────────────────
def set_redis_connection(pool: ConnectionPool, client: Redis) -> None:
    """
    Устанавливает подключение к Redis.

    Вызывается при старте приложения из lifespan-контекста.

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
    """
    Очищает ссылки на подключение к Redis.

    Вызывается при остановке приложения из lifespan-контекста.
    """
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

    :return: Пул соединений или None, если не инициализирован.
    """
    return _pool


def is_redis_connected() -> bool:
    """
    Проверяет, инициализировано ли подключение к Redis.

    :return: True, если клиент инициализирован.
    """
    return _client is not None


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции для работы с ключами кэша
# ──────────────────────────────────────────────────────────────────────────────
def _infer_resource_id(
    kwargs: dict[str, Any],
    resource_id_type: type | tuple[type, ...],
) -> int | str:
    """Infer the resource ID from a dictionary of keyword arguments.

    Parameters
    ----------
    kwargs: Dict[str, Any]
        A dictionary of keyword arguments.
    resource_id_type: Union[type, Tuple[type, ...]]
        The expected type of the resource ID, which can be integer (int) or a string (str).

    Returns
    -------
    Union[None, int, str]
        The inferred resource ID. If it cannot be inferred or does not match the expected type, it returns None.

    Note
    ----
        - When `resource_id_type` is `int`, the function looks for an argument with the key 'id'.
        - When `resource_id_type` is `str`, it attempts to infer the resource ID as a string.
    """
    resource_id: int | str | None = None
    for arg_name, arg_value in kwargs.items():
        if isinstance(arg_value, resource_id_type):
            if (resource_id_type is int) and ("id" in arg_name):
                resource_id = arg_value

            elif (resource_id_type is int) and ("id" not in arg_name):
                pass

            elif resource_id_type is str:
                resource_id = arg_value

    if resource_id is None:
        raise CacheIdentificationInferenceError()

    return resource_id


def _extract_data_inside_brackets(input_string: str) -> list[str]:
    """Extract data inside curly brackets from a given string using regular expressions.

    Parameters
    ----------
    input_string: str
        The input string in which to find data enclosed within curly brackets.

    Returns
    -------
    List[str]
        A list of strings containing the data found inside the curly brackets within the input string.

    Example
    -------
    >>> _extract_data_inside_brackets("The {quick} brown {fox} jumps over the {lazy} dog.")
    ['quick', 'fox', 'lazy']
    """
    data_inside_brackets: list[str] = re.findall(r"{(.*?)}", input_string)
    return data_inside_brackets


def _construct_data_dict(
    data_inside_brackets: list[str],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Construct a dictionary based on data inside brackets and keyword arguments.

    Parameters
    ----------
    data_inside_brackets: List[str]
        A list of keys inside brackets.
    kwargs: Dict[str, Any]
        A dictionary of keyword arguments.

    Returns
    -------
    Dict[str, Any]: A dictionary with keys from data_inside_brackets and corresponding values from kwargs.
    """
    data_dict: dict[str, Any] = {}
    for key in data_inside_brackets:
        data_dict[key] = kwargs[key]
    return data_dict


def _format_prefix(prefix: str, kwargs: dict[str, Any]) -> str:
    """Format a prefix using keyword arguments.

    Parameters
    ----------
    prefix: str
        The prefix template to be formatted.
    kwargs: Dict[str, Any]
        A dictionary of keyword arguments.

    Returns
    -------
    str: The formatted prefix.
    """
    data_inside_brackets = _extract_data_inside_brackets(prefix)
    data_dict = _construct_data_dict(data_inside_brackets, kwargs)
    formatted_prefix: str = prefix.format(**data_dict)
    return formatted_prefix


def _format_extra_data(
    to_invalidate_extra: dict[str, str],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Format extra data based on provided templates and keyword arguments.

    This function takes a dictionary of templates and their associated values and a dictionary of keyword arguments.
    It formats the templates with the corresponding values from the keyword arguments and returns a dictionary
    where keys are the formatted templates and values are the associated keyword argument values.

    Parameters
    ----------
    to_invalidate_extra: Dict[str, str]
        A dictionary where keys are templates and values are the associated values.
    kwargs: Dict[str, Any]
        A dictionary of keyword arguments.

    Returns
    -------
        Dict[str, Any]: A dictionary where keys are formatted templates and values
        are associated keyword argument values.
    """
    formatted_extra: dict[str, Any] = {}
    for prefix, id_template in to_invalidate_extra.items():
        formatted_prefix = _format_prefix(prefix, kwargs)
        extracted_id = _extract_data_inside_brackets(id_template)[0]
        formatted_extra[formatted_prefix] = kwargs[extracted_id]

    return formatted_extra


async def _delete_keys_by_pattern(pattern: str) -> None:
    """Delete keys from Redis that match a given pattern using the SCAN command.

    This function iteratively scans the Redis key space for keys that match a specific pattern
    and deletes them. It uses the SCAN command to efficiently find keys, which is more
    performance-friendly compared to the KEYS command, especially for large datasets.

    The function scans the key space in an iterative manner using a cursor-based approach.
    It retrieves a batch of keys matching the pattern on each iteration and deletes them
    until no matching keys are left.

    Parameters
    ----------
    pattern: str
        The pattern to match keys against. The pattern can include wildcards,
        such as '*' for matching any character sequence. Example: 'user:*'

    Notes
    -----
    - The SCAN command is used with a count of 100 to retrieve keys in batches.
      This count can be adjusted based on the size of your dataset and Redis performance.

    - The function uses the delete command to remove keys in bulk. If the dataset
      is extremely large, consider implementing additional logic to handle bulk deletion
      more efficiently.

    - Be cautious with patterns that could match a large number of keys, as deleting
      many keys simultaneously may impact the performance of the Redis server.
    """
    redis_client = get_redis_client()

    cursor: int = 0
    first_iteration: bool = True
    while cursor != 0 or first_iteration:
        first_iteration = False
        cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
        if keys:
            await redis_client.delete(*keys)


# ──────────────────────────────────────────────────────────────────────────────
# Декоратор кэширования
# ──────────────────────────────────────────────────────────────────────────────
def cache(
    key_prefix: str,
    resource_id_name: str | None = None,
    expiration: int = 3600,
    resource_id_type: type | tuple[type, ...] = int,
    to_invalidate_extra: dict[str, Any] | None = None,
    pattern_to_invalidate_extra: list[str] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Cache decorator for FastAPI endpoints.

    This decorator enables caching the results of FastAPI endpoint functions to improve response times
    and reduce the load on the application by storing and retrieving data in a cache.

    Parameters
    ----------
    key_prefix: str
        A unique prefix to identify the cache key.
    resource_id_name: Any, optional
        The name of the resource ID argument in the decorated function. If provided, it is used directly;
        otherwise, the resource ID is inferred from the function's arguments.
    expiration: int, optional
        The expiration time for the cached data in seconds. Defaults to 3600 seconds (1 hour).
    resource_id_type: Union[type, Tuple[type, ...]], default int
        The expected type of the resource ID.
        This can be a single type (e.g., int) or a tuple of types (e.g., (int, str)).
        Defaults to int. This is used only if resource_id_name is not provided.
    to_invalidate_extra: Dict[str, Any] | None, optional
        A dictionary where keys are cache key prefixes and values are templates for cache key suffixes.
        These keys are invalidated when the decorated function is called with a method other than GET.
    pattern_to_invalidate_extra: List[str] | None, optional
        A list of string patterns for cache keys that should be invalidated when the decorated function is called.
        This allows for bulk invalidation of cache keys based on a matching pattern.

    Returns
    -------
    Callable
        A decorator function that can be applied to FastAPI endpoint functions.

    Example usage
    -------------

    ```python
    from fastapi import FastAPI, Request
    from my_module import cache  # Replace with your actual module and imports

    app = FastAPI()

    # Define a sample endpoint with caching
    @app.get("/sample/{resource_id}")
    @cache(key_prefix="sample_data", expiration=3600, resource_id_type=int)
    async def sample_endpoint(request: Request, resource_id: int):
        # Your endpoint logic here
        return {"data": "your_data"}
    ```

    This decorator caches the response data of the endpoint function using a unique cache key.
    The cached data is retrieved for GET requests, and the cache is invalidated for other types of requests.

    Advanced Example Usage
    -------------
    ```python
    from fastapi import FastAPI, Request
    from my_module import cache

    app = FastAPI()


    @app.get("/users/{user_id}/items")
    @cache(key_prefix="user_items", resource_id_name="user_id", expiration=1200)
    async def read_user_items(request: Request, user_id: int):
        # Endpoint logic to fetch user's items
        return {"items": "user specific items"}


    @app.put("/items/{item_id}")
    @cache(
        key_prefix="item_data",
        resource_id_name="item_id",
        to_invalidate_extra={"user_items": "{user_id}"},
        pattern_to_invalidate_extra=["user_*_items:*"],
    )
    async def update_item(request: Request, item_id: int, data: dict, user_id: int):
        # Update logic for an item
        # Invalidate both the specific item cache and all user-specific item lists
        return {"status": "updated"}
    ```

    In this example:
    - When reading user items, the response is cached under a key formed with 'user_items' prefix and 'user_id'.
    - When updating an item, the cache for this specific item (under 'item_data:item_id') and all caches with keys
      starting with 'user_{user_id}_items:' are invalidated. The `to_invalidate_extra` parameter specifically targets
      the cache for user-specific item lists, while `pattern_to_invalidate_extra` allows bulk invalidation of all keys
      matching the pattern 'user_*_items:*', covering all users.

    Note
    ----
    - resource_id_type is used only if resource_id is not passed.
    - `to_invalidate_extra` and `pattern_to_invalidate_extra` are used for cache invalidation on methods other than GET.
    - Using `pattern_to_invalidate_extra` can be resource-intensive on large datasets. Use it judiciously and
      consider the potential impact on Redis performance.
    """

    def wrapper(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def inner(request: Request, *args: Any, **kwargs: Any) -> Response:
            redis_client = get_redis_client()

            if resource_id_name:
                resource_id = kwargs[resource_id_name]
            else:
                resource_id = _infer_resource_id(
                    kwargs=kwargs,
                    resource_id_type=resource_id_type,
                )

            formatted_key_prefix = _format_prefix(key_prefix, kwargs)
            cache_key = f"{formatted_key_prefix}:{resource_id}"

            if request.method == "GET":
                if (
                    to_invalidate_extra is not None
                    or pattern_to_invalidate_extra is not None
                ):
                    raise InvalidRequestError()

                cached_data = await redis_client.get(cache_key)
                if cached_data:
                    return json.loads(cached_data.decode())

            result = await func(request, *args, **kwargs)

            if request.method == "GET":
                serializable_data = jsonable_encoder(result)
                serialized_data = json.dumps(serializable_data)

                await redis_client.set(cache_key, serialized_data)
                await redis_client.expire(cache_key, expiration)

            else:
                await redis_client.delete(cache_key)
                if to_invalidate_extra is not None:
                    formatted_extra = _format_extra_data(to_invalidate_extra, kwargs)
                    for prefix, id_value in formatted_extra.items():
                        extra_cache_key = f"{prefix}:{id_value}"
                        await redis_client.delete(extra_cache_key)

                if pattern_to_invalidate_extra is not None:
                    for pattern in pattern_to_invalidate_extra:
                        formatted_pattern = _format_prefix(pattern, kwargs)
                        await _delete_keys_by_pattern(formatted_pattern + "*")

            return result

        return inner

    return wrapper
