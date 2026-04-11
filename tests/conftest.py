"""Общие фикстуры для тестов."""

from __future__ import annotations

import os
import shutil
import tempfile

from collections.abc import Generator

import pytest

# ── Переопределение переменных окружения для тестов ──────────────────────────
# Выполняется ДО любых импортов из приложения, чтобы pydantic-settings
# использовал тестовые пути вместо Docker-путей из .env файла.
_TEST_TMP_DIR: str = tempfile.mkdtemp(prefix="interview_coach_test_")

os.environ["APP_LOG_DIR"] = os.path.join(_TEST_TMP_DIR, "logs")
os.environ["INTERVIEW_LOG_DIR"] = os.path.join(_TEST_TMP_DIR, "interview_logs")
os.environ["LANGFUSE_ENABLED"] = "false"

import src.app.observability.alerts as _alerts_module  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_alert_manager_global() -> Generator[None, None, None]:
    """Сбрасывает глобальный ``_alert_manager`` после каждого теста."""
    original = _alerts_module._alert_manager
    yield
    _alerts_module._alert_manager = original


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Удаляет временную директорию после завершения всех тестов."""
    shutil.rmtree(_TEST_TMP_DIR, ignore_errors=True)
