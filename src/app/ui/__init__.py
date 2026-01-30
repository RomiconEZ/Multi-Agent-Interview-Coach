"""
Модуль пользовательского интерфейса.

Содержит Gradio приложение для интервью.
"""

from .gradio_app import create_gradio_interface, launch_app

__all__ = [
    "create_gradio_interface",
    "launch_app",
]
