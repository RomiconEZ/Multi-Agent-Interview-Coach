"""
Перечисление вариантов окружения.
"""

from enum import Enum


class EnvironmentOption(Enum):
    """Варианты окружения приложения."""

    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"
