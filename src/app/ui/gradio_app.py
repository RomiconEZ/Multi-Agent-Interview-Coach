"""
Gradio интерфейс для Multi-Agent Interview Coach.
"""

from __future__ import annotations

import asyncio
import logging

from pathlib import Path
from typing import Any

import gradio as gr

from ..core.config import settings
from ..core.logger_setup import get_system_logger, setup_logging
from ..interview import InterviewSession, create_interview_session

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)

_current_session: InterviewSession | None = None
_last_log_path: Path | None = None
_last_detailed_log_path: Path | None = None


def _run_async(coro: Any) -> Any:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        import nest_asyncio

        nest_asyncio.apply()

    return loop.run_until_complete(coro)


async def _start_interview_async(
    model: str,
) -> tuple[str, str, list[tuple[str | None, str | None]]]:
    """
    Асинхронно начинает интервью.

    :return: Tuple (статус, очищенный инпут, история чата).
    """
    global _current_session, _last_log_path, _last_detailed_log_path

    if _current_session is not None:
        await _current_session.close()

    _last_log_path = None
    _last_detailed_log_path = None

    model_name = model.strip() if model.strip() else None
    _current_session = await create_interview_session(model_name)

    greeting = await _current_session.start()

    status = f"✅ Интервью начато | Модель: {_current_session._llm_client.model}"
    history: list[tuple[str | None, str | None]] = [(None, greeting)]

    return status, "", history


def start_interview(model: str) -> tuple[str, str, list[tuple[str | None, str | None]]]:
    """Синхронная обёртка для старта интервью."""
    return _run_async(_start_interview_async(model))


async def _send_message_async(
    message: str,
    history: list[tuple[str | None, str | None]],
) -> tuple[str, str, list[tuple[str | None, str | None]], str, str | None, str | None]:
    """
    Асинхронно обрабатывает сообщение.

    :return: Tuple (статус, очищенный инпут, история, фидбэк, путь_лог, путь_детальный).
    """
    global _current_session, _last_log_path, _last_detailed_log_path

    if _current_session is None:
        return "❌ Сначала начните интервью", message, history, "", None, None

    if not message.strip():
        return "❌ Введите сообщение", "", history, "", None, None

    history.append((message, None))

    response, is_finished = await _current_session.process_message(message.strip())

    history[-1] = (message, response)

    if is_finished:
        feedback, summary_path, detailed_path = await _current_session.generate_feedback()
        feedback_text = feedback.to_formatted_string()

        # Добавляем метрики токенов
        metrics = _current_session.get_session_metrics()
        if metrics:
            feedback_text += "\n\n" + metrics.to_summary_string()

        _last_log_path = summary_path
        _last_detailed_log_path = detailed_path

        status = "✅ Интервью завершено. Фидбэк сгенерирован."
        return status, "", history, feedback_text, str(summary_path), str(detailed_path)

    status = (
        f"✅ Ход {_current_session.state.current_turn if _current_session.state else '?'}"
    )
    return status, "", history, "", None, None


def send_message(
    message: str,
    history: list[tuple[str | None, str | None]],
) -> tuple[str, str, list[tuple[str | None, str | None]], str, str | None, str | None]:
    """Синхронная обёртка для отправки сообщения."""
    return _run_async(_send_message_async(message, history))


async def _stop_interview_async(
    history: list[tuple[str | None, str | None]],
) -> tuple[str, list[tuple[str | None, str | None]], str, str | None, str | None]:
    """Асинхронно завершает интервью."""
    global _current_session, _last_log_path, _last_detailed_log_path

    if _current_session is None:
        return "❌ Нет активного интервью", history, "", None, None

    if _current_session._state:
        _current_session._state.is_active = False

    feedback, summary_path, detailed_path = await _current_session.generate_feedback()
    feedback_text = feedback.to_formatted_string()

    # Добавляем метрики токенов
    metrics = _current_session.get_session_metrics()
    if metrics:
        feedback_text += "\n\n" + metrics.to_summary_string()

    _last_log_path = summary_path
    _last_detailed_log_path = detailed_path

    history.append(("Стоп интервью", "Интервью завершено. Формирую фидбэк..."))

    return (
        "✅ Интервью завершено",
        history,
        feedback_text,
        str(summary_path),
        str(detailed_path),
    )


def stop_interview(
    history: list[tuple[str | None, str | None]],
) -> tuple[str, list[tuple[str | None, str | None]], str, str | None, str | None]:
    return _run_async(_stop_interview_async(history))


def create_gradio_interface() -> gr.Blocks:
    with gr.Blocks(title="Multi-Agent Interview Coach", theme=gr.themes.Soft()) as app:
        gr.Markdown(
            """
            # 🎯 Multi-Agent Interview Coach

            Система технического интервью с AI-агентами:
            - **Observer Agent** — анализирует ответы, выявляет галлюцинации
            - **Interviewer Agent** — ведёт диалог, адаптирует сложность
            - **Evaluator Agent** — формирует финальный фидбэк

            **Как использовать:**
            1. Нажмите "🚀 Начать интервью"
            2. Представьтесь (имя, позиция, опыт)
            3. Отвечайте на вопросы
            4. Скажите "стоп" для получения фидбэка
            """
        )

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### ⚙️ Настройки")

                model_input = gr.Textbox(
                    label="Модель LLM (опционально)",
                    placeholder=settings.LITELLM_MODEL,
                    value="",
                )

                start_btn = gr.Button("🚀 Начать интервью", variant="primary")
                stop_btn = gr.Button("🛑 Завершить и получить фидбэк", variant="stop")

                status_output = gr.Textbox(label="Статус", interactive=False)

            with gr.Column(scale=2):
                gr.Markdown("### 💬 Диалог")

                chatbot = gr.Chatbot(label="Интервью", height=400, type="tuples")

                with gr.Row():
                    msg_input = gr.Textbox(
                        label="Ваш ответ",
                        placeholder="Введите ответ...",
                        lines=2,
                        scale=4,
                    )
                    send_btn = gr.Button("📤 Отправить", scale=1)

        with gr.Row():
            with gr.Column():
                gr.Markdown("### 📊 Финальный фидбэк")
                feedback_output = gr.Textbox(label="Фидбэк", lines=20, interactive=False)

            with gr.Column():
                gr.Markdown("### 📁 Скачать логи")

                main_log_file = gr.File(label="📄 Основной лог", interactive=False)
                detailed_log_file = gr.File(label="📄 Детальный лог", interactive=False)

        start_btn.click(
            fn=start_interview,
            inputs=[model_input],
            outputs=[status_output, msg_input, chatbot],
        )

        send_btn.click(
            fn=send_message,
            inputs=[msg_input, chatbot],
            outputs=[
                status_output,
                msg_input,
                chatbot,
                feedback_output,
                main_log_file,
                detailed_log_file,
            ],
        )

        msg_input.submit(
            fn=send_message,
            inputs=[msg_input, chatbot],
            outputs=[
                status_output,
                msg_input,
                chatbot,
                feedback_output,
                main_log_file,
                detailed_log_file,
            ],
        )

        stop_btn.click(
            fn=stop_interview,
            inputs=[chatbot],
            outputs=[
                status_output,
                chatbot,
                feedback_output,
                main_log_file,
                detailed_log_file,
            ],
        )

    return app


def launch_app(
    server_name: str = "0.0.0.0",
    server_port: int = 7860,
    share: bool = False,
) -> None:
    """
    Запускает Gradio приложение.

    :param server_name: Хост сервера.
    :param server_port: Порт сервера.
    :param share: Создать публичную ссылку.
    """
    setup_logging()
    logger.info(f"Launching Gradio app on {server_name}:{server_port}")

    app = create_gradio_interface()
    app.launch(server_name=server_name, server_port=server_port, share=share)
