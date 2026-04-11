"""
Circuit breaker для защиты от каскадных сбоев при недоступности LLM API.

Реализует паттерн Circuit Breaker с тремя состояниями:

- **CLOSED** — нормальная работа, запросы проходят к LLM.
- **OPEN** — сервис признан недоступным, запросы отклоняются
  немедленно без обращения к сети.
- **HALF_OPEN** — пробный режим: один запрос пропускается
  для проверки восстановления сервиса.

Переход CLOSED → OPEN происходит после ``failure_threshold``
последовательных сбоев.
Переход OPEN → HALF_OPEN — автоматически через ``recovery_timeout`` секунд.
Переход HALF_OPEN → CLOSED — при успешном запросе.
Переход HALF_OPEN → OPEN — при неуспешном запросе.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum

from ..core.logger_setup import get_system_logger

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


class CircuitState(str, Enum):
    """Состояние circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Исключение: circuit breaker в открытом состоянии, запрос отклонён."""


class CircuitBreaker:
    """
    Circuit breaker для защиты от каскадных сбоев при недоступности внешнего сервиса.

    :param failure_threshold: Количество последовательных сбоев для перехода в OPEN.
    :param recovery_timeout: Время в секундах до перехода из OPEN в HALF_OPEN.
    """

    def __init__(
        self,
        failure_threshold: int,
        recovery_timeout: float,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._state: CircuitState = CircuitState.CLOSED

    @property
    def state(self) -> CircuitState:
        """Возвращает текущее состояние с учётом таймаута восстановления."""
        if self._state == CircuitState.OPEN:
            elapsed: float = time.monotonic() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    f"Circuit breaker transitioned to HALF_OPEN "
                    f"after {elapsed:.1f}s recovery timeout"
                )
        return self._state

    @property
    def failure_count(self) -> int:
        """Возвращает текущее количество последовательных сбоев."""
        return self._failure_count

    def check(self) -> None:
        """
        Проверяет, можно ли выполнить запрос.

        :raises CircuitBreakerOpen: Если circuit breaker в состоянии OPEN.
        """
        current_state: CircuitState = self.state
        if current_state == CircuitState.OPEN:
            remaining: float = self._recovery_timeout - (
                time.monotonic() - self._last_failure_time
            )
            raise CircuitBreakerOpen(
                f"Circuit breaker is OPEN after {self._failure_count} "
                f"consecutive failures. Recovery in {max(0, remaining):.0f}s."
            )

    def record_success(self) -> None:
        """Фиксирует успешный запрос и сбрасывает счётчик сбоев."""
        if self._state != CircuitState.CLOSED:
            logger.info(f"Circuit breaker reset to CLOSED from {self._state.value}")
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Фиксирует неуспешный запрос и открывает circuit breaker при достижении порога."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            was_not_open: bool = self._state != CircuitState.OPEN
            self._state = CircuitState.OPEN
            if was_not_open:
                logger.warning(
                    f"Circuit breaker OPENED after {self._failure_count} "
                    f"consecutive failures (threshold={self._failure_threshold})"
                )
                self._fire_open_alert()

    def _fire_open_alert(self) -> None:
        """
        Асинхронно отправляет CRITICAL-алерт о переходе circuit breaker в OPEN.

        Использует ``asyncio.get_running_loop().create_task`` для неблокирующей
        отправки. Если event loop недоступен, алерт пропускается (ошибка логируется).
        Значения снимаются в snapshot до создания корутины, чтобы избежать
        гонки с последующими мутациями состояния.
        """
        failure_count: int = self._failure_count
        failure_threshold: int = self._failure_threshold
        recovery_timeout: float = self._recovery_timeout

        try:
            from ..observability.alerts import get_alert_manager

            alert_mgr = get_alert_manager()

            async def _send() -> None:
                await alert_mgr.fire_critical(
                    source="CircuitBreaker",
                    message=(
                        f"Circuit breaker transitioned to OPEN after "
                        f"{failure_count} consecutive failures "
                        f"(threshold={failure_threshold}, "
                        f"recovery={recovery_timeout}s)"
                    ),
                    metadata={
                        "failure_count": failure_count,
                        "failure_threshold": failure_threshold,
                        "recovery_timeout": recovery_timeout,
                    },
                )

            loop = asyncio.get_running_loop()
            _ = loop.create_task(_send())
        except RuntimeError:
            logger.debug("No running event loop, skipping circuit breaker alert")
        except Exception as exc:
            logger.warning(f"Failed to fire circuit breaker alert: {exc}")
