"""Общие фикстуры для тестов."""

from __future__ import annotations

import pytest

import src.app.observability.alerts as _alerts_module


@pytest.fixture(autouse=True)
def _reset_alert_manager_global() -> None:
    """Сбрасывает глобальный ``_alert_manager`` после каждого теста."""
    original = _alerts_module._alert_manager
    yield  # type: ignore[misc]
    _alerts_module._alert_manager = original
