#!/usr/bin/env python3
"""
Точка входа для запуска Gradio интерфейса.
"""

from __future__ import annotations

import argparse

from .core.logger_setup import setup_logging
from .ui import launch_app


def parse_args() -> argparse.Namespace:
    """Парсит аргументы командной строки."""
    parser = argparse.ArgumentParser(description="Multi-Agent Interview Coach - Gradio Interface")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=7860, help="Port to run the server")
    parser.add_argument("--share", action="store_true", help="Create a public shareable link")
    return parser.parse_args()


def main() -> None:
    """Главная функция запуска."""
    setup_logging()
    args = parse_args()

    print(f"\n{'=' * 60}")
    print("🎯 Multi-Agent Interview Coach")
    print(f"{'=' * 60}")
    print(f"Starting server on http://{args.host}:{args.port}")
    if args.share:
        print("Public link will be created...")
    print(f"{'=' * 60}\n")

    launch_app(server_name=args.host, server_port=args.port, share=args.share)


if __name__ == "__main__":
    main()