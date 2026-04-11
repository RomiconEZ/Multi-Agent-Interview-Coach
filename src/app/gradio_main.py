#!/usr/bin/env python3
"""
Точка входа для запуска Gradio интерфейса.
"""

from __future__ import annotations

import argparse

from .core.config import get_settings
from .core.logger_setup import get_system_logger, setup_logging
from .observability.alerts import configure_alert_manager
from .ui import launch_app

logger = get_system_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Парсит аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="Multi-Agent Interview Coach - Gradio Interface"
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Host to bind the server"
    )
    parser.add_argument("--port", type=int, default=7860, help="Port to run the server")
    parser.add_argument(
        "--share", action="store_true", help="Create a public shareable link"
    )
    return parser.parse_args()


def main() -> None:
    """Главная функция запуска."""
    settings = get_settings()
    settings.ensure_directories()
    setup_logging()
    configure_alert_manager()
    args = parse_args()

    logger.info("Multi-Agent Interview Coach")
    logger.info(f"Starting server on http://{args.host}:{args.port}")
    if args.share:
        logger.info("Public link will be created...")

    launch_app(server_name=args.host, server_port=args.port, share=args.share)


if __name__ == "__main__":
    main()
