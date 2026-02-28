"""
Утилита для получения списка доступных моделей из LiteLLM API.

Предоставляет функцию для запроса эндпоинта ``/v1/models``
и извлечения идентификаторов моделей.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..core.config import settings
from ..core.logger_setup import get_system_logger

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)

_MODELS_ENDPOINT: str = "/v1/models"


async def fetch_available_models(
        base_url: str,
        api_key: str,
        timeout: float,
) -> list[str]:
    """
    Запрашивает список доступных моделей у LiteLLM API.

    Обращается к эндпоинту ``GET /v1/models`` и возвращает
    отсортированный список идентификаторов моделей.

    :param base_url: Базовый URL LiteLLM API.
    :param api_key: API-ключ для авторизации.
    :param timeout: Таймаут запроса в секундах.
    :return: Отсортированный список имён моделей.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url: str = f"{base_url.rstrip('/')}{_MODELS_ENDPOINT}"

    try:
        async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout)
        ) as client:
            response: httpx.Response = await client.get(url, headers=headers)
            response.raise_for_status()

        data: dict[str, Any] = response.json()
        model_ids: list[str] = [
            entry["id"]
            for entry in data.get("data", [])
            if isinstance(entry, dict) and "id" in entry
        ]

        model_ids.sort()
        logger.info(f"Fetched {len(model_ids)} models from LiteLLM: {url}")
        return model_ids

    except httpx.HTTPStatusError as exc:
        logger.warning(
            f"LiteLLM models endpoint returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:300]}"
        )
        return []

    except httpx.RequestError as exc:
        logger.warning(f"Failed to connect to LiteLLM models endpoint: {exc}")
        return []

    except Exception as exc:
        logger.error(f"Unexpected error fetching models: {type(exc).__name__}: {exc}")
        return []


def fetch_available_models_sync(
        base_url: str,
        api_key: str,
        timeout: float,
) -> list[str]:
    """
    Синхронная версия получения списка моделей из LiteLLM API.

    :param base_url: Базовый URL LiteLLM API.
    :param api_key: API-ключ для авторизации.
    :param timeout: Таймаут запроса в секундах.
    :return: Отсортированный список имён моделей.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url: str = f"{base_url.rstrip('/')}{_MODELS_ENDPOINT}"

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            response: httpx.Response = client.get(url, headers=headers)
            response.raise_for_status()

        data: dict[str, Any] = response.json()
        model_ids: list[str] = [
            entry["id"]
            for entry in data.get("data", [])
            if isinstance(entry, dict) and "id" in entry
        ]

        model_ids.sort()
        logger.info(f"Fetched {len(model_ids)} models from LiteLLM (sync): {url}")
        return model_ids

    except httpx.HTTPStatusError as exc:
        logger.warning(
            f"LiteLLM models endpoint returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:300]}"
        )
        return []

    except httpx.RequestError as exc:
        logger.warning(f"Failed to connect to LiteLLM models endpoint (sync): {exc}")
        return []

    except Exception as exc:
        logger.error(
            f"Unexpected error fetching models (sync): {type(exc).__name__}: {exc}"
        )
        return []


def get_models_for_ui() -> list[str]:
    """
    Возвращает список моделей для отображения в интерфейсе.

    Использует настройки из конфигурации приложения.
    Если получить список не удалось, возвращает список
    с моделью по умолчанию из настроек.

    :return: Список имён моделей.
    """
    models: list[str] = fetch_available_models_sync(
        base_url=settings.LITELLM_BASE_URL,
        api_key=settings.LITELLM_API_KEY,
        timeout=settings.LITELLM_MODELS_FETCH_TIMEOUT,
    )

    if not models:
        default_model: str = settings.LITELLM_MODEL
        logger.info(f"No models fetched from LiteLLM, using default: {default_model}")
        return [default_model]

    return models