"""
Модуль для работы с LLM.

Содержит клиент для LiteLLM API, утилиты для получения списка моделей
и гибкий парсер ответов LLM.
"""

from .client import LLMClient, LLMClientError, create_llm_client
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
    "LLMClient",
    "LLMClientError",
    "create_llm_client",
    "fetch_available_models",
    "fetch_available_models_sync",
    "get_models_for_ui",
    "extract_json_from_llm_response",
    "extract_reasoning_from_llm_response",
]