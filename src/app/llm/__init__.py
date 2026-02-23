"""
Модуль для работы с LLM.

Содержит клиент для LiteLLM API и утилиты для получения списка моделей.
"""

from .client import LLMClient, LLMClientError, create_llm_client
from .models import (
    fetch_available_models,
    fetch_available_models_sync,
    get_models_for_ui,
)

__all__ = [
    "LLMClient",
    "LLMClientError",
    "create_llm_client",
    "fetch_available_models",
    "fetch_available_models_sync",
    "get_models_for_ui",
]
