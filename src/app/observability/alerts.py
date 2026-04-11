"""
Модуль алертинга для мониторинга критических событий системы.

Предоставляет механизм оповещения о сбоях, деградации производительности
и критических состояниях компонентов (circuit breaker, LLM недоступность,
превышение порогов ошибок).
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ..core.logger_setup import get_system_logger
from .langfuse_client import get_langfuse_tracker

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


class AlertSeverity(str, Enum):
    """Уровень критичности алерта."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert(BaseModel, frozen=True):
    """
    Неизменяемая модель алерта.

    :ivar severity: Уровень критичности.
    :ivar source: Источник алерта (имя компонента).
    :ivar message: Описание события.
    :ivar timestamp: Время возникновения (UTC).
    :ivar metadata: Дополнительные данные о событии.
    """

    severity: AlertSeverity
    source: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class AlertChannel(Protocol):
    """Протокол канала доставки алертов."""

    async def send(self, alert: Alert) -> None:
        """
        Отправляет алерт через канал.

        :param alert: Алерт для отправки.
        """
        ...


class LogAlertChannel:
    """
    Канал алертов через систему логирования.

    Маппинг severity → logging level:
    - INFO → logging.INFO
    - WARNING → logging.WARNING
    - CRITICAL → logging.CRITICAL
    """

    _SEVERITY_TO_LEVEL: dict[AlertSeverity, int] = {
        AlertSeverity.INFO: logging.INFO,
        AlertSeverity.WARNING: logging.WARNING,
        AlertSeverity.CRITICAL: logging.CRITICAL,
    }

    async def send(self, alert: Alert) -> None:
        """
        Отправляет алерт в лог.

        :param alert: Алерт для логирования.
        """
        level: int = self._SEVERITY_TO_LEVEL.get(alert.severity, logging.WARNING)
        meta_str: str = f" | metadata={alert.metadata}" if alert.metadata else ""
        logger.log(
            level,
            f"ALERT [{alert.severity.value.upper()}] "
            f"source={alert.source} | {alert.message}{meta_str}",
        )


class LangfuseAlertChannel:
    """
    Канал алертов через Langfuse observability.

    Создаёт trace в Langfuse с тегами ``alert`` и уровнем severity,
    позволяя фильтровать алерты в UI Langfuse.
    При недоступности или отключённом Langfuse операция пропускается.
    """

    async def send(self, alert: Alert) -> None:
        """
        Отправляет алерт в Langfuse как trace.

        :param alert: Алерт для отправки.
        """
        tracker = get_langfuse_tracker()
        tracker.log_alert(
            severity=alert.severity.value,
            source=alert.source,
            message=alert.message,
            timestamp=alert.timestamp.isoformat(),
            metadata=alert.metadata,
        )


class AlertManager:
    """
    Менеджер алертов — центральная точка отправки оповещений.

    Рассылает алерты по всем зарегистрированным каналам.
    Гарантирует, что сбой одного канала не блокирует остальные.

    :param channels: Кортеж каналов доставки алертов.
    """

    def __init__(self, channels: tuple[AlertChannel, ...]) -> None:
        self._channels: tuple[AlertChannel, ...] = channels

    async def fire(self, alert: Alert) -> None:
        """
        Рассылает алерт по всем каналам.

        :param alert: Алерт для отправки.
        """
        for channel in self._channels:
            try:
                await channel.send(alert)
            except Exception as exc:
                tb: str = traceback.format_exc().replace("\n", " | ")
                logger.warning(
                    f"Alert channel {type(channel).__name__} failed: "
                    f"{exc} | traceback: {tb}"
                )

    async def fire_warning(
        self,
        source: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Создаёт и отправляет WARNING-алерт.

        :param source: Источник алерта.
        :param message: Описание события.
        :param metadata: Дополнительные данные.
        """
        alert = Alert(
            severity=AlertSeverity.WARNING,
            source=source,
            message=message,
            metadata=metadata or {},
        )
        await self.fire(alert)

    async def fire_critical(
        self,
        source: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Создаёт и отправляет CRITICAL-алерт.

        :param source: Источник алерта.
        :param message: Описание события.
        :param metadata: Дополнительные данные.
        """
        alert = Alert(
            severity=AlertSeverity.CRITICAL,
            source=source,
            message=message,
            metadata=metadata or {},
        )
        await self.fire(alert)


_alert_manager: AlertManager | None = None


def _create_channels() -> tuple[AlertChannel, ...]:
    """
    Создаёт стандартный набор каналов доставки алертов.

    :return: Кортеж каналов (LogAlertChannel, LangfuseAlertChannel).
    """
    return (LogAlertChannel(), LangfuseAlertChannel())


async def close_alert_manager() -> None:
    """
    Сбрасывает глобальный менеджер алертов.

    Безопасно вызывать повторно или когда менеджер не был инициализирован.
    """
    global _alert_manager
    if _alert_manager is not None:
        _alert_manager = None
        logger.info("Alert manager closed")


def configure_alert_manager() -> AlertManager:
    """
    Конфигурирует глобальный менеджер алертов.

    Регистрирует ``LogAlertChannel`` и ``LangfuseAlertChannel``.

    :return: Сконфигурированный менеджер алертов.
    """
    global _alert_manager

    if _alert_manager is not None:
        logger.warning(
            "Alert manager is being reconfigured; "
            "call close_alert_manager() first to release previous resources"
        )

    channels: tuple[AlertChannel, ...] = _create_channels()
    _alert_manager = AlertManager(channels=channels)
    logger.info(f"Alert manager configured with {len(channels)} channel(s)")
    return _alert_manager


def get_alert_manager() -> AlertManager:
    """
    Возвращает глобальный менеджер алертов.

    Если менеджер не был сконфигурирован, создаёт экземпляр
    с набором каналов по умолчанию (fallback).

    :return: Экземпляр AlertManager.
    """
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager(channels=_create_channels())
    return _alert_manager
