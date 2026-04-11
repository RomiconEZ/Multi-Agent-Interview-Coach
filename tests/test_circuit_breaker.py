"""
Тесты для модуля circuit breaker.

Покрывает: переходы состояний, пороги сбоев, таймаут восстановления,
сброс при успехе, проверку check().
"""

from __future__ import annotations

import time

import pytest

from src.app.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
)


class TestCircuitBreakerInitialState:
    """Тесты начального состояния circuit breaker."""

    def test_initial_state_is_closed(self) -> None:
        """При создании circuit breaker находится в состоянии CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        assert cb.state == CircuitState.CLOSED

    def test_initial_failure_count_is_zero(self) -> None:
        """При создании счётчик сбоев равен нулю."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        assert cb.failure_count == 0


class TestCircuitBreakerTransitions:
    """Тесты переходов состояний circuit breaker."""

    def test_closed_to_open_on_threshold(self) -> None:
        """Переход CLOSED → OPEN при достижении порога сбоев."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_failure_count_increments(self) -> None:
        """Счётчик сбоев корректно увеличивается."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)

        for i in range(1, 4):
            cb.record_failure()
            assert cb.failure_count == i

    def test_open_to_half_open_after_recovery_timeout(self) -> None:
        """Переход OPEN → HALF_OPEN после истечения таймаута восстановления."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self) -> None:
        """Переход HALF_OPEN → CLOSED при успешном запросе."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_to_open_on_failure(self) -> None:
        """Переход HALF_OPEN → OPEN при сбое в пробном запросе."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerCheck:
    """Тесты метода check()."""

    def test_check_passes_when_closed(self) -> None:
        """check() не вызывает исключение в состоянии CLOSED."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
        cb.check()

    def test_check_raises_when_open(self) -> None:
        """check() вызывает CircuitBreakerOpen в состоянии OPEN."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpen) as exc_info:
            cb.check()

        assert "OPEN" in str(exc_info.value)
        assert "1 consecutive failures" in str(exc_info.value)

    def test_check_passes_when_half_open(self) -> None:
        """check() пропускает запрос в состоянии HALF_OPEN."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        cb.check()


class TestCircuitBreakerReset:
    """Тесты сброса circuit breaker."""

    def test_success_resets_failure_count(self) -> None:
        """record_success() сбрасывает счётчик сбоев."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_success_from_closed_stays_closed(self) -> None:
        """record_success() в CLOSED не меняет состояние."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestCircuitBreakerEdgeCases:
    """Тесты граничных случаев."""

    def test_threshold_one(self) -> None:
        """Порог сбоев = 1: один сбой сразу открывает breaker."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 1

    def test_multiple_successes_keep_closed(self) -> None:
        """Множественные успехи не меняют состояние CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        for _ in range(10):
            cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_interleaved_failures_and_successes(self) -> None:
        """Успех между сбоями сбрасывает счётчик."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        cb.record_success()
        assert cb.failure_count == 0

        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED

    def test_open_stays_open_before_recovery(self) -> None:
        """Circuit breaker остаётся OPEN до истечения recovery_timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.state == CircuitState.OPEN

    def test_check_includes_remaining_time(self) -> None:
        """Сообщение CircuitBreakerOpen содержит оставшееся время восстановления."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=120.0)
        cb.record_failure()

        with pytest.raises(CircuitBreakerOpen) as exc_info:
            cb.check()

        error_message: str = str(exc_info.value)
        assert "Recovery" in error_message

    def test_recovery_timeout_boundary(self) -> None:
        """Проверка перехода точно на границе таймаута восстановления."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

    def test_rapid_open_close_cycle(self) -> None:
        """Быстрый цикл OPEN → HALF_OPEN → CLOSED."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)

        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

        cb.record_failure()
        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED
