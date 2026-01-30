"""
Модуль для работы с LLM.

Содержит клиент для LiteLLM API.
"""

from .client import LLMClient, LLMClientError, create_llm_client

__all__ = [
    "LLMClient",
    "LLMClientError",
    "create_llm_client",
]
