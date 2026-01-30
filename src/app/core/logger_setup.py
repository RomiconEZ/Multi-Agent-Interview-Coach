from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from .config import settings

APP_TIMEZONE: Final[timezone] = timezone(timedelta(hours=settings.APP_TZ_OFFSET))


class TZFormatter(logging.Formatter):
    """
    Форматтер, выставляющий время в заданном часовом поясе.

    Использует глобальную константу APP_TIMEZONE для форматирования
    временных меток в логах.
    """

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, APP_TIMEZONE)
        return dt.strftime(datefmt) if datefmt else dt.isoformat(timespec="seconds")


class ConsoleTZFormatter(TZFormatter):
    """
    Форматтер для консоли: добавляет ID в персональных логах
    и гарантирует наличие поля ``log_type`` для сторонних записей.
    """

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "log_type"):
            record.log_type = "EXTERNAL"
        elif record.log_type == "PERSONAL":
            item_id = getattr(record, "id", None)
            if item_id is not None:
                record.log_type = f"{record.log_type} [ID:{item_id}]"
        return super().format(record)


class SystemLogFilter(logging.Filter):
    """
    Пропускает только системные логи (``record.log_type == 'SYSTEM'``).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "log_type", None) == "SYSTEM"


class PersonalLogFilter(logging.Filter):
    """
    Пропускает только персональные логи (``record.log_type == 'PERSONAL'``).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "log_type", None) == "PERSONAL"


SYSTEM_LOG_FORMAT: Final[str] = "%(asctime)s - %(levelname)s - %(log_type)s - %(message)s"
PERSONAL_LOG_FORMAT: Final[str] = "%(asctime)s - %(levelname)s - %(log_type)s ID:%(id)s - %(message)s"
CONSOLE_FORMAT: Final[str] = "%(asctime)s - %(levelname)s - %(log_type)s - %(message)s"


def _create_file_handler(
        path: Path,
        level: int,
        log_format: str,
        log_filter: logging.Filter,
        max_bytes: int,
        backup_count: int,
) -> RotatingFileHandler:
    """
    Создаёт RotatingFileHandler с заданными параметрами.

    :param path: Путь к лог-файлу.
    :param level: Уровень логирования.
    :param log_format: Формат сообщений.
    :param log_filter: Фильтр для сообщений.
    :param max_bytes: Максимальный размер файла перед ротацией.
    :param backup_count: Количество резервных копий.
    :return: Настроенный обработчик.
    """
    handler = RotatingFileHandler(
        path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(TZFormatter(log_format, "%Y-%m-%d %H:%M:%S"))
    handler.addFilter(log_filter)
    return handler


def _clear_handlers(logger: logging.Logger) -> None:
    """
    Удаляет все обработчики у логгера.
    """
    while logger.handlers:
        handler = logger.handlers.pop()
        handler.close()


def _attach_handlers(logger: logging.Logger, handlers: Iterable[logging.Handler]) -> None:
    """
    Добавляет обработчики к логгеру.
    """
    for handler in handlers:
        logger.addHandler(handler)


def set_external_loggers_levels() -> None:
    """
    Снижает уровень детализации логов сторонних библиотек до WARNING.
    Также отключает propagate, чтобы сообщения не всплывали в root при DEBUG.
    """
    for name in (
            "multipart.multipart",
            "python_multipart.multipart",
            "urllib3",
            "urllib3.connectionpool",
            "httpx",
            "httpcore",
            "anyio",
    ):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        lg.propagate = False


def setup_logging(force_reconfigure: bool = False) -> None:
    """
    Настраивает корневой логгер и три обработчика:

    1) system.log – уровень DEBUG, только системные сообщения;
    2) personal.log – уровень DEBUG, только персональные сообщения;
    3) консоль – уровень DEBUG, все сообщения (внешние тоже).

    При повторном вызове без ``force_reconfigure`` повторная настройка не выполняется.

    :param force_reconfigure: Принудительно переконфигурировать логгер,
        даже если обработчики уже настроены.
    """
    root_logger = logging.getLogger()

    if root_logger.handlers and not force_reconfigure:
        return

    _clear_handlers(root_logger)
    root_logger.setLevel(logging.DEBUG)

    system_handler = _create_file_handler(
        path=settings.SYSTEM_LOG_PATH,
        level=logging.DEBUG,
        log_format=SYSTEM_LOG_FORMAT,
        log_filter=SystemLogFilter(),
        max_bytes=settings.LOG_MAX_BYTES,
        backup_count=settings.LOG_BACKUP_COUNT,
    )
    personal_handler = _create_file_handler(
        path=settings.PERSONAL_LOG_PATH,
        level=logging.DEBUG,
        log_format=PERSONAL_LOG_FORMAT,
        log_filter=PersonalLogFilter(),
        max_bytes=settings.LOG_MAX_BYTES,
        backup_count=settings.LOG_BACKUP_COUNT,
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ConsoleTZFormatter(CONSOLE_FORMAT, "%Y-%m-%d %H:%M:%S"))

    _attach_handlers(root_logger, (system_handler, personal_handler, console_handler))
    set_external_loggers_levels()

    get_system_logger(__name__).info("System logging configured.")


def get_system_logger(name: str) -> logging.LoggerAdapter[logging.Logger]:
    """
    Возвращает адаптер для системных логов.

    :param name: Имя логгера (обычно ``__name__`` вызывающего модуля).
    :return: LoggerAdapter с предустановленным типом лога SYSTEM.
    """
    base_logger = logging.getLogger(name)
    return logging.LoggerAdapter(base_logger, {"log_type": "SYSTEM"})


def get_personal_logger(request_id: str | None, name: str) -> logging.LoggerAdapter[logging.Logger]:
    """
    Возвращает адаптер для персональных логов.

    :param request_id: Идентификатор запроса. Если None, используется «UNDEFINED».
    :param name: Имя логгера (обычно ``__name__`` вызывающего модуля).
    :return: LoggerAdapter с предустановленными типом лога PERSONAL и id.
    """
    final_id = request_id if request_id is not None else "UNDEFINED"
    base_logger = logging.getLogger(name)
    return logging.LoggerAdapter(base_logger, {"log_type": "PERSONAL", "id": final_id})