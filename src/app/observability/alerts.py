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

import httpx
from pydantic import BaseModel, Field

from ..core.logger_setup import get_system_logger

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


class WebhookAlertChannel:
    """
    Канал алертов через HTTP webhook.

    Отправляет POST-запрос с JSON-телом на указанный URL.
    При сбое доставки логирует ошибку, не пробрасывает исключение.
    Переиспользует единый ``httpx.AsyncClient`` для всех отправок,
    чтобы избежать создания нового TCP-соединения на каждый алерт.

    :param url: URL вебхука.
    :param timeout_seconds: Таймаут HTTP-запроса.
    """

    def __init__(self, url: str, timeout_seconds: float) -> None:
        self._url = url
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """
        Возвращает переиспользуемый HTTP-клиент, создавая его при необходимости.

        :return: Экземпляр ``httpx.AsyncClient``.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def send(self, alert: Alert) -> None:
        """
        Отправляет алерт на webhook.

        :param alert: Алерт для отправки.
        """
        payload: dict[str, Any] = {
            "severity": alert.severity.value,
            "source": alert.source,
            "message": alert.message,
            "timestamp": alert.timestamp.isoformat(),
            "metadata": alert.metadata,
        }
        try:
            client: httpx.AsyncClient = self._get_client()
            response: httpx.Response = await client.post(
                self._url,
                json=payload,
            )
            if response.status_code >= 400:
                logger.warning(
                    f"Webhook alert delivery failed: "
                    f"status={response.status_code}, url={self._url}"
                )
            else:
                logger.debug(
                    f"Webhook alert delivered: "
                    f"status={response.status_code}, url={self._url}"
                )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            tb: str = traceback.format_exc().replace("\n", " | ")
            logger.warning(f"Webhook alert delivery error: {exc} | traceback: {tb}")

    async def close(self) -> None:
        """Закрывает HTTP-клиент, освобождая ресурсы."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class AlertManager:
    """
    Менеджер алертов — центральная точка отправки оповещений.

    Рассылает алерты по всем зарегистрированным каналам.
    Гарантирует, что сбой одного канала не блокирует остальные.

    :param channels: Список каналов доставки алертов.
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


def configure_alert_manager(
    webhook_url: str | None,
    webhook_timeout: float,
) -> AlertManager:
    """
    Конфигурирует глобальный менеджер алертов на основе настроек.

    Всегда регистрирует ``LogAlertChannel``.
    Если задан ``webhook_url``, дополнительно регистрирует ``WebhookAlertChannel``.

    :param webhook_url: URL вебхука для отправки алертов (None — не использовать).
    :param webhook_timeout: Таймаут HTTP-запроса к вебхуку в секундах.
    :return: Сконфигурированный менеджер алертов.
    """
    global _alert_manager

    channels: list[AlertChannel] = [LogAlertChannel()]
    if webhook_url:
        channels.append(
            WebhookAlertChannel(url=webhook_url, timeout_seconds=webhook_timeout)
        )
        logger.info(f"Webhook alert channel configured: {webhook_url}")

    _alert_manager = AlertManager(channels=tuple(channels))
    logger.info(f"Alert manager configured with {len(channels)} channel(s)")
    return _alert_manager


def get_alert_manager() -> AlertManager:
    """
    Возвращает глобальный менеджер алертов.

    Если менеджер не был сконфигурирован, создаёт экземпляр
    с единственным ``LogAlertChannel`` (fallback).

    :return: Экземпляр AlertManager.
    """
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager(channels=(LogAlertChannel(),))
    return _alert_manager
