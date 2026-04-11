"""
Модуль для работы с LLM.

Содержит клиент для LiteLLM API, утилиты для получения списка моделей
и гибкий парсер ответов LLM.
"""

from .cache import (
    LLMCacheBackend,
    NullLLMCache,
    RedisLLMCache,
    compute_cache_key,
    create_llm_cache,
)
from .client import LLMClient, LLMClientError, close_shared_llm_cache, create_llm_client
from .models import (
    fetch_available_models,
    fetch_available_models_sync,
    get_models_for_ui,
)
from .response_parser import (
    extract_json_from_llm_response,
    extract_reasoning_from_llm_response,
)

__all__ = [
    "LLMCacheBackend",
    "LLMClient",
    "LLMClientError",
    "NullLLMCache",
    "RedisLLMCache",
    "close_shared_llm_cache",
    "compute_cache_key",
    "create_llm_cache",
    "create_llm_client",
    "extract_json_from_llm_response",
    "extract_reasoning_from_llm_response",
    "fetch_available_models",
    "fetch_available_models_sync",
    "get_models_for_ui",
]
