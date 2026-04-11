"""
Тесты для модуля алертинга.

Покрывает: Alert модель, LogAlertChannel, LangfuseAlertChannel (мок),
AlertManager, фабрику configure_alert_manager, get_alert_manager.
"""

from __future__ import annotations

import logging

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydantic import ValidationError

from src.app.observability.alerts import (
    Alert,
    AlertManager,
    AlertSeverity,
    LangfuseAlertChannel,
    LogAlertChannel,
    configure_alert_manager,
    get_alert_manager,
)


class TestAlertModel:
    """Тесты модели Alert."""

    def test_alert_creation(self) -> None:
        """Alert создаётся с корректными полями."""
        alert = Alert(
            severity=AlertSeverity.WARNING,
            source="test_source",
            message="something happened",
        )
        assert alert.severity == AlertSeverity.WARNING
        assert alert.source == "test_source"
        assert alert.message == "something happened"
        assert isinstance(alert.timestamp, datetime)
        assert alert.metadata == {}

    def test_alert_with_metadata(self) -> None:
        """Alert принимает произвольные метаданные."""
        meta: dict[str, Any] = {"key": "value", "count": 42}
        alert = Alert(
            severity=AlertSeverity.CRITICAL,
            source="src",
            message="msg",
            metadata=meta,
        )
        assert alert.metadata == meta

    def test_alert_is_frozen(self) -> None:
        """Alert является неизменяемой моделью."""
        alert = Alert(
            severity=AlertSeverity.INFO,
            source="src",
            message="msg",
        )
        with pytest.raises(ValidationError):
            alert.source = "new_source"  # type: ignore[misc]

    def test_alert_timestamp_is_utc(self) -> None:
        """Timestamp алерта имеет UTC timezone."""
        alert = Alert(
            severity=AlertSeverity.INFO,
            source="src",
            message="msg",
        )
        assert alert.timestamp.tzinfo == timezone.utc


class TestAlertSeverity:
    """Тесты перечисления AlertSeverity."""

    def test_severity_values(self) -> None:
        """Все уровни критичности доступны."""
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.CRITICAL.value == "critical"

    def test_severity_is_string_enum(self) -> None:
        """AlertSeverity является строковым перечислением."""
        assert isinstance(AlertSeverity.WARNING, str)
        assert AlertSeverity.WARNING == "warning"


class TestLogAlertChannel:
    """Тесты канала алертов через логирование."""

    async def test_send_warning_logs_at_warning_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """WARNING алерт логируется на уровне WARNING."""
        channel = LogAlertChannel()
        alert = Alert(
            severity=AlertSeverity.WARNING,
            source="test_component",
            message="disk usage high",
        )
        with caplog.at_level(logging.WARNING):
            await channel.send(alert)

        assert any("ALERT" in record.message for record in caplog.records)
        assert any("WARNING" in record.message for record in caplog.records)
        assert any("test_component" in record.message for record in caplog.records)

    async def test_send_critical_logs_at_critical_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """CRITICAL алерт логируется на уровне CRITICAL."""
        channel = LogAlertChannel()
        alert = Alert(
            severity=AlertSeverity.CRITICAL,
            source="circuit_breaker",
            message="breaker opened",
        )
        with caplog.at_level(logging.CRITICAL):
            await channel.send(alert)

        assert any("CRITICAL" in record.message for record in caplog.records)

    async def test_send_info_logs_at_info_level(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """INFO алерт логируется на уровне INFO."""
        channel = LogAlertChannel()
        alert = Alert(
            severity=AlertSeverity.INFO,
            source="cache",
            message="cache cleared",
        )
        with caplog.at_level(logging.INFO):
            await channel.send(alert)

        assert any("INFO" in record.message for record in caplog.records)

    async def test_send_includes_metadata(self, caplog: pytest.LogCaptureFixture) -> None:
        """Метаданные включаются в лог-сообщение."""
        channel = LogAlertChannel()
        alert = Alert(
            severity=AlertSeverity.WARNING,
            source="src",
            message="msg",
            metadata={"model": "gpt-4"},
        )
        with caplog.at_level(logging.WARNING):
            await channel.send(alert)

        assert any("gpt-4" in record.message for record in caplog.records)


class TestLangfuseAlertChannel:
    """Тесты канала алертов через Langfuse."""

    async def test_send_calls_log_alert(self) -> None:
        """send() вызывает tracker.log_alert с корректными параметрами."""
        channel = LangfuseAlertChannel()
        alert = Alert(
            severity=AlertSeverity.CRITICAL,
            source="llm_client",
            message="all retries exhausted",
            metadata={"model": "local_llm"},
        )

        mock_tracker = MagicMock()
        mock_tracker.log_alert = MagicMock()

        with patch(
            "src.app.observability.alerts.get_langfuse_tracker",
            return_value=mock_tracker,
        ):
            await channel.send(alert)

        mock_tracker.log_alert.assert_called_once_with(
            severity="critical",
            source="llm_client",
            message="all retries exhausted",
            timestamp=alert.timestamp.isoformat(),
            metadata={"model": "local_llm"},
        )

    async def test_send_with_empty_metadata(self) -> None:
        """send() корректно обрабатывает пустые метаданные."""
        channel = LangfuseAlertChannel()
        alert = Alert(
            severity=AlertSeverity.WARNING,
            source="src",
            message="msg",
        )

        mock_tracker = MagicMock()
        mock_tracker.log_alert = MagicMock()

        with patch(
            "src.app.observability.alerts.get_langfuse_tracker",
            return_value=mock_tracker,
        ):
            await channel.send(alert)

        mock_tracker.log_alert.assert_called_once()
        call_kwargs = mock_tracker.log_alert.call_args[1]
        assert call_kwargs["metadata"] == {}

    async def test_send_all_severity_levels(self) -> None:
        """send() корректно передаёт все уровни severity."""
        channel = LangfuseAlertChannel()

        for severity in AlertSeverity:
            alert = Alert(
                severity=severity,
                source="test",
                message="test",
            )

            mock_tracker = MagicMock()
            mock_tracker.log_alert = MagicMock()

            with patch(
                "src.app.observability.alerts.get_langfuse_tracker",
                return_value=mock_tracker,
            ):
                await channel.send(alert)

            call_kwargs = mock_tracker.log_alert.call_args[1]
            assert call_kwargs["severity"] == severity.value


class TestAlertManager:
    """Тесты менеджера алертов."""

    async def test_fire_sends_to_all_channels(self) -> None:
        """fire() отправляет алерт во все зарегистрированные каналы."""
        channel_a = AsyncMock()
        channel_a.send = AsyncMock()
        channel_b = AsyncMock()
        channel_b.send = AsyncMock()

        manager = AlertManager(channels=(channel_a, channel_b))
        alert = Alert(
            severity=AlertSeverity.WARNING,
            source="test",
            message="test",
        )

        await manager.fire(alert)
        channel_a.send.assert_awaited_once_with(alert)
        channel_b.send.assert_awaited_once_with(alert)

    async def test_fire_continues_if_channel_fails(self) -> None:
        """Сбой одного канала не блокирует остальные."""
        channel_a = AsyncMock()
        channel_a.send = AsyncMock(side_effect=RuntimeError("channel_a down"))
        channel_b = AsyncMock()
        channel_b.send = AsyncMock()

        manager = AlertManager(channels=(channel_a, channel_b))
        alert = Alert(
            severity=AlertSeverity.CRITICAL,
            source="test",
            message="test",
        )

        await manager.fire(alert)
        channel_b.send.assert_awaited_once_with(alert)

    async def test_fire_warning_creates_warning_alert(self) -> None:
        """fire_warning() создаёт алерт с уровнем WARNING."""
        channel = AsyncMock()
        channel.send = AsyncMock()
        manager = AlertManager(channels=(channel,))

        await manager.fire_warning(
            source="test_src",
            message="warning message",
            metadata={"key": "val"},
        )

        channel.send.assert_awaited_once()
        sent_alert: Alert = channel.send.call_args[0][0]
        assert sent_alert.severity == AlertSeverity.WARNING
        assert sent_alert.source == "test_src"
        assert sent_alert.message == "warning message"
        assert sent_alert.metadata == {"key": "val"}

    async def test_fire_critical_creates_critical_alert(self) -> None:
        """fire_critical() создаёт алерт с уровнем CRITICAL."""
        channel = AsyncMock()
        channel.send = AsyncMock()
        manager = AlertManager(channels=(channel,))

        await manager.fire_critical(
            source="circuit_breaker",
            message="breaker opened",
            metadata={"count": 5},
        )

        channel.send.assert_awaited_once()
        sent_alert: Alert = channel.send.call_args[0][0]
        assert sent_alert.severity == AlertSeverity.CRITICAL
        assert sent_alert.metadata == {"count": 5}

    async def test_fire_with_no_channels(self) -> None:
        """fire() с пустым списком каналов не вызывает ошибок."""
        manager = AlertManager(channels=())
        alert = Alert(
            severity=AlertSeverity.INFO,
            source="test",
            message="test",
        )
        await manager.fire(alert)

    async def test_fire_warning_default_metadata(self) -> None:
        """fire_warning() без метаданных использует пустой dict."""
        channel = AsyncMock()
        channel.send = AsyncMock()
        manager = AlertManager(channels=(channel,))

        await manager.fire_warning(source="s", message="m")

        sent_alert: Alert = channel.send.call_args[0][0]
        assert sent_alert.metadata == {}

    async def test_fire_critical_default_metadata(self) -> None:
        """fire_critical() без метаданных использует пустой dict."""
        channel = AsyncMock()
        channel.send = AsyncMock()
        manager = AlertManager(channels=(channel,))

        await manager.fire_critical(source="s", message="m")

        sent_alert: Alert = channel.send.call_args[0][0]
        assert sent_alert.metadata == {}


class TestConfigureAlertManager:
    """Тесты фабрики конфигурации менеджера алертов."""

    def test_configure_creates_two_channels(self) -> None:
        """Создаётся менеджер с LogAlertChannel и LangfuseAlertChannel."""
        manager = configure_alert_manager()
        assert isinstance(manager, AlertManager)
        assert len(manager._channels) == 2
        assert isinstance(manager._channels[0], LogAlertChannel)
        assert isinstance(manager._channels[1], LangfuseAlertChannel)


class TestGetAlertManager:
    """Тесты получения глобального менеджера алертов."""

    def test_get_returns_configured_manager(self) -> None:
        """get_alert_manager() возвращает ранее сконфигурированный менеджер."""
        configured = configure_alert_manager()
        retrieved = get_alert_manager()
        assert retrieved is configured

    def test_get_creates_fallback_if_not_configured(self) -> None:
        """get_alert_manager() создаёт fallback менеджер если не был сконфигурирован."""
        import src.app.observability.alerts as alerts_module

        alerts_module._alert_manager = None
        manager = get_alert_manager()
        assert isinstance(manager, AlertManager)
        assert len(manager._channels) == 2
        assert isinstance(manager._channels[0], LogAlertChannel)
        assert isinstance(manager._channels[1], LangfuseAlertChannel)
