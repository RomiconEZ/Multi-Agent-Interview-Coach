"""
Общие константы, используемые в middleware и других модулях приложения.

Данный модуль содержит неизменяемые константы, которые используются
в нескольких местах приложения для обеспечения единообразия.
"""

from __future__ import annotations

import re

from typing import Final, FrozenSet, Pattern

REQUEST_ID_PATTERN: Final[Pattern[str]] = re.compile(
    r"^\d+-\d+-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
"""
Регулярное выражение для валидации формата request_id.

Формат: {number}-{number}-{UUID v4}
Пример: 123-456-a1b2c3d4-e5f6-7890-abcd-ef1234567890
"""

SENSITIVE_KEYS: Final[FrozenSet[str]] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "apikey",
        "x-api-key",
        "client_secret",
        "private_key",
        "jwt",
        "id_token",
        "session",
        "set-cookie",
    }
)
"""
Набор ключей, значения которых должны быть скрыты при логировании.

Используется для редактирования чувствительных данных в логах запросов и ответов.
Все ключи приведены к нижнему регистру для case-insensitive сравнения.
"""

DEFAULT_REQUEST_ID_HEADER_NAMES: Final[tuple[str, ...]] = ("x-request-id",)
"""
Заголовки HTTP, в которых по умолчанию ищется request_id.
"""
