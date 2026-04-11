"""Утилиты для безопасной работы с URL."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def mask_url(url: str) -> str:
    """
    Маскирует секретные части URL для безопасного логирования.

    Скрывает пароль в ``userinfo`` и обрезает path до первых 8 символов,
    так как webhook URL и Redis URL могут содержать встроенные токены.

    :param url: Исходный URL.
    :return: URL с замаскированными секретными частями.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "<unparseable-url>"

    host: str = parsed.hostname or ""
    port_suffix: str = f":{parsed.port}" if parsed.port else ""

    if parsed.password:
        user_part: str = parsed.username or ""
        netloc: str = f"{user_part}:***@{host}{port_suffix}"
        masked = parsed._replace(netloc=netloc)
        return urlunparse(masked)

    path_preview: str = parsed.path[:8] + "..." if len(parsed.path) > 8 else parsed.path
    return f"{parsed.scheme}://{host}{port_suffix}{path_preview}"
