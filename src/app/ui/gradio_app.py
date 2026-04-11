# Multi-Agent-Interview-Coach/src/app/ui/gradio_app.py
"""
Gradio интерфейс для Multi-Agent Interview Coach.

Предоставляет профессиональный пользовательский интерфейс
для проведения тренировочных технических интервью с AI-агентами.
"""

from __future__ import annotations

import asyncio
import logging

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import gradio as gr

from ..core.config import settings
from ..core.logger_setup import get_system_logger, setup_logging
from ..interview import InterviewSession, create_interview_session
from ..llm.models import get_models_for_ui
from ..schemas.agent_settings import (
    AgentSettings,
    InterviewConfig,
    SingleAgentConfig,
)
from .styles import HEADER_HTML, MAIN_CSS

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)

_current_session: InterviewSession | None = None
_last_log_path: Path | None = None
_last_detailed_log_path: Path | None = None


def _run_async(coro: Any) -> Any:
    """
    Выполняет корутину в синхронном контексте Gradio.

    Используется только для обработчиков, которым требуется синхронный вызов
    (например, ``start_interview``, ``reset_interview``).
    Обработчики в горячем пути отправки сообщений объявлены как ``async def``
    напрямую, чтобы не блокировать event loop Gradio.

    :param coro: Корутина для выполнения.
    :return: Результат выполнения корутины.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        import nest_asyncio

        nest_asyncio.apply()

    return loop.run_until_complete(coro)


def _build_interview_config(
    model: str,
    max_turns: int,
    job_description: str,
    obs_temp: float,
    obs_tokens: int,
    int_temp: float,
    int_tokens: int,
    eval_temp: float,
    eval_tokens: int,
) -> InterviewConfig:
    """
    Собирает конфигурацию интервью из параметров UI.

    :param model: Имя модели LLM.
    :param max_turns: Максимальное количество ходов.
    :param job_description: Описание вакансии.
    :param obs_temp: Температура Observer.
    :param obs_tokens: Макс. токенов Observer.
    :param int_temp: Температура Interviewer.
    :param int_tokens: Макс. токенов Interviewer.
    :param eval_temp: Температура Evaluator.
    :param eval_tokens: Макс. токенов Evaluator.
    :return: Конфигурация интервью.
    """
    return InterviewConfig(
        model=model.strip() if model and model.strip() else None,
        max_turns=max_turns,
        job_description=job_description.strip()
        if job_description and job_description.strip()
        else None,
        agent_settings=AgentSettings(
            observer=SingleAgentConfig(
                temperature=obs_temp,
                max_tokens=obs_tokens,
                generation_retries=2,
            ),
            interviewer=SingleAgentConfig(
                temperature=int_temp,
                max_tokens=int_tokens,
                generation_retries=0,
            ),
            evaluator=SingleAgentConfig(
                temperature=eval_temp,
                max_tokens=eval_tokens,
                generation_retries=2,
            ),
        ),
    )


def _enable_input_controls() -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Возвращает обновления для разблокировки элементов ввода.

    :return: Tuple (обновление send_btn, обновление msg_input).
    """
    return gr.update(interactive=True), gr.update(interactive=True)


def _disable_input_controls() -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Возвращает обновления для блокировки элементов ввода.

    :return: Tuple (обновление send_btn, обновление msg_input).
    """
    return gr.update(interactive=False), gr.update(interactive=False)


def _append_assistant_message(
    history: list[dict[str, str | None]],
    content: str,
) -> list[dict[str, str | None]]:
    """
    Добавляет сообщение ассистента в историю чата.

    :param history: История чата.
    :param content: Текст сообщения ассистента.
    :return: Новая история чата.
    """
    updated_history: list[dict[str, str | None]] = list(history)
    updated_history.append({"role": "assistant", "content": content})
    return updated_history


async def _start_interview_async(
    model: str,
    max_turns: int,
    job_description: str,
    obs_temp: float,
    obs_tokens: int,
    int_temp: float,
    int_tokens: int,
    eval_temp: float,
    eval_tokens: int,
) -> tuple[
    str,
    dict[str, Any],
    list[dict[str, str | None]],
    str,
    str | None,
    str | None,
    dict[str, Any],
]:
    """
    Асинхронно начинает новое интервью.

    :return: Tuple (статус, msg_input, история чата, фидбэк, лог, детальный лог, send_btn).
    """
    global _current_session, _last_log_path, _last_detailed_log_path

    if _current_session is not None:
        await _current_session.close()

    _last_log_path = None
    _last_detailed_log_path = None

    config: InterviewConfig = _build_interview_config(
        model,
        max_turns,
        job_description,
        obs_temp,
        obs_tokens,
        int_temp,
        int_tokens,
        eval_temp,
        eval_tokens,
    )

    try:
        _current_session = await create_interview_session(config)
        greeting: str = await _current_session.start()
    except Exception as e:
        logger.error(f"Failed to start interview: {type(e).__name__}: {e}")
        _current_session = None
        return (
            f"❌ Ошибка запуска интервью: {e}",
            gr.update(value="", interactive=False),
            [],
            "",
            None,
            None,
            gr.update(interactive=False),
        )

    actual_model: str = _current_session._llm_client.model
    jd_indicator: str = " | 📋 Вакансия задана" if config.job_description else ""
    status: str = f"✅ Интервью начато | Модель: {actual_model}{jd_indicator}"
    history: list[dict[str, str | None]] = [{"role": "assistant", "content": greeting}]

    return (
        status,
        gr.update(value="", interactive=True),
        history,
        "",
        None,
        None,
        gr.update(interactive=True),
    )


def start_interview_prepare() -> (
    tuple[
        str,
        dict[str, Any],
        list[dict[str, str | None]],
        str,
        None,
        None,
        dict[str, Any],
    ]
):
    """
    Мгновенно обновляет UI при нажатии «Начать интервью».

    Сразу меняет статус и блокирует ввод, не ожидая генерации приветствия.

    :return: Tuple (статус, msg_input, история чата, фидбэк, лог, детальный лог, send_btn).
    """
    send_btn_disabled, msg_input_disabled = _disable_input_controls()
    return (
        "⏳ Запуск интервью...",
        msg_input_disabled,
        [],
        "",
        None,
        None,
        send_btn_disabled,
    )


def start_interview(
    model: str,
    max_turns: int,
    job_description: str,
    obs_temp: float,
    obs_tokens: int,
    int_temp: float,
    int_tokens: int,
    eval_temp: float,
    eval_tokens: int,
) -> tuple[
    str,
    dict[str, Any],
    list[dict[str, str | None]],
    str,
    str | None,
    str | None,
    dict[str, Any],
]:
    """Синхронная обёртка для старта интервью."""
    return _run_async(  # type: ignore[no-any-return]
        _start_interview_async(
            model,
            max_turns,
            job_description,
            obs_temp,
            obs_tokens,
            int_temp,
            int_tokens,
            eval_temp,
            eval_tokens,
        )
    )


def add_user_message(
    message: str,
    history: list[dict[str, str | None]],
) -> tuple[dict[str, Any], list[dict[str, str | None]], dict[str, Any], Any]:
    """
    Мгновенно добавляет сообщение пользователя в историю чата, очищает и блокирует ввод.

    Выполняется с ``queue=False`` — обходит очередь Gradio и обновляет UI
    немедленно, не дожидаясь ответа от LLM. Является чисто синхронной функцией:
    не вызывает LLM и не блокирует event loop.

    Если сообщение пустое — не вносит изменений (кнопка и поле остаются без изменений).

    :param message: Текст сообщения кандидата.
    :param history: Текущая история чата.
    :return: Tuple (обновление msg_input, обновлённая история, обновление send_btn, статус).
    """
    if not message or not message.strip():
        return gr.update(), history, gr.update(), gr.update()

    updated_history: list[dict[str, str | None]] = list(history)
    updated_history.append({"role": "user", "content": message})

    return (
        gr.update(value="", interactive=False),
        updated_history,
        gr.update(interactive=False),
        "⏳ Генерация ответа...",
    )


async def bot_respond(
    history: list[dict[str, str | None]],
) -> AsyncGenerator[
    tuple[
        str,
        list[dict[str, str | None]],
        str,
        str | None,
        str | None,
        dict[str, Any],
        dict[str, Any],
    ],
    None,
]:
    """
    Асинхронно обрабатывает последнее сообщение пользователя и возвращает ответ агента.

    Реализован как async generator для возможности отображения промежуточных
    состояний UI (например, сообщения «Формирую фидбэк...» перед генерацией).

    При завершении интервью:
    1. Первый yield — в чат добавляется «Интервью завершено. Формирую фидбэк...».
    2. Второй yield — в чат добавляется «Фидбэк сгенерирован...», а также отображается фидбэк.

    При обычном ходе — единственный yield с ответом и разблокировкой ввода.

    :param history: История чата с уже добавленным сообщением пользователя.
    :return: AsyncGenerator, yield-ящий tuple
        (статус, история, фидбэк, лог, детальный лог, send_btn, msg_input).
    """
    global _current_session, _last_log_path, _last_detailed_log_path

    send_btn_enabled, msg_input_enabled = _enable_input_controls()
    send_btn_disabled, msg_input_disabled = _disable_input_controls()

    if _current_session is None:
        yield (
            "⚠️ Сначала начните интервью",
            history,
            "",
            None,
            None,
            send_btn_disabled,
            msg_input_disabled,
        )
        return

    user_message: str = ""
    for msg in reversed(history):
        if msg.get("role") == "user":
            user_message = str(msg.get("content") or "")
            break

    if not user_message.strip():
        yield (
            "⚠️ Сообщение пустое",
            history,
            "",
            None,
            None,
            send_btn_enabled,
            msg_input_enabled,
        )
        return

    response: str
    is_finished: bool

    try:
        response, is_finished = await _current_session.process_message(
            user_message.strip()
        )
    except Exception as e:
        logger.error(f"Unexpected error in process_message: {type(e).__name__}: {e}")
        yield (
            f"❌ Ошибка: {e}",
            history,
            "",
            None,
            None,
            send_btn_enabled,
            msg_input_enabled,
        )
        return

    updated_history: list[dict[str, str | None]] = _append_assistant_message(
        history,
        response,
    )

    if is_finished:
        updated_history = _append_assistant_message(
            updated_history,
            "⏳ Интервью завершено. Формирую фидбэк...",
        )
        yield (
            "⏳ Формирую фидбэк...",
            updated_history,
            "",
            None,
            None,
            send_btn_disabled,
            msg_input_disabled,
        )

        try:
            (
                feedback,
                summary_path,
                detailed_path,
            ) = await _current_session.generate_feedback()
        except Exception as e:
            logger.error(f"Feedback generation failed: {type(e).__name__}: {e}")
            updated_history = _append_assistant_message(
                updated_history,
                f"❌ Ошибка генерации фидбэка: {e}",
            )
            yield (
                f"❌ Ошибка генерации фидбэка: {e}",
                updated_history,
                "",
                None,
                None,
                send_btn_disabled,
                msg_input_disabled,
            )
            return

        feedback_text: str = feedback.to_formatted_string()

        metrics = _current_session.get_session_metrics()
        if metrics:
            feedback_text += "\n\n" + metrics.to_summary_string()

        _last_log_path = summary_path
        _last_detailed_log_path = detailed_path

        updated_history = _append_assistant_message(
            updated_history,
            "✅ Фидбэк сгенерирован. Перейдите на вкладку «Фидбэк».",
        )

        yield (
            "✅ Интервью завершено. Фидбэк сгенерирован.",
            updated_history,
            feedback_text,
            str(summary_path),
            str(detailed_path),
            send_btn_disabled,
            msg_input_disabled,
        )
        return

    current_turn: str = str(
        _current_session.state.current_turn if _current_session.state else "?"
    )
    max_turns_val: str = str(_current_session._config.max_turns)
    status: str = f"💬 Ход {current_turn}/{max_turns_val}"

    yield (
        status,
        updated_history,
        "",
        None,
        None,
        send_btn_enabled,
        msg_input_enabled,
    )


async def stop_interview(
    history: list[dict[str, str | None]],
) -> AsyncGenerator[
    tuple[
        str,
        list[dict[str, str | None]],
        str,
        str | None,
        str | None,
        dict[str, Any],
        dict[str, Any],
    ],
    None,
]:
    """
    Асинхронно завершает интервью и генерирует фидбэк.

    Реализован как async generator для двухэтапного обновления UI:
    1. Немедленно добавляет в чат сообщение «Интервью завершено. Формирую фидбэк...»
       и блокирует ввод.
    2. После генерации добавляет ещё одно сообщение «Фидбэк сгенерирован...»
       и выводит фидбэк.

    :param history: История чата.
    :return: AsyncGenerator, yield-ящий tuple
        (статус, история, фидбэк, лог, детальный лог, send_btn, msg_input).
    """
    global _current_session, _last_log_path, _last_detailed_log_path

    send_btn_disabled, msg_input_disabled = _disable_input_controls()

    if _current_session is None:
        yield (
            "⚠️ Нет активного интервью",
            history,
            "",
            None,
            None,
            send_btn_disabled,
            msg_input_disabled,
        )
        return

    if _current_session._state:
        _current_session._state.is_active = False

    updated_history: list[dict[str, str | None]] = _append_assistant_message(
        history,
        "⏳ Интервью завершено. Формирую фидбэк...",
    )

    yield (
        "⏳ Формирую фидбэк...",
        updated_history,
        "",
        None,
        None,
        send_btn_disabled,
        msg_input_disabled,
    )

    try:
        (
            feedback,
            summary_path,
            detailed_path,
        ) = await _current_session.generate_feedback()
    except Exception as e:
        logger.error(f"Feedback generation failed on stop: {type(e).__name__}: {e}")
        updated_history = _append_assistant_message(
            updated_history,
            f"❌ Ошибка генерации фидбэка: {e}",
        )
        yield (
            f"❌ Ошибка генерации фидбэка: {e}",
            updated_history,
            "",
            None,
            None,
            send_btn_disabled,
            msg_input_disabled,
        )
        return

    feedback_text: str = feedback.to_formatted_string()

    metrics = _current_session.get_session_metrics()
    if metrics:
        feedback_text += "\n\n" + metrics.to_summary_string()

    _last_log_path = summary_path
    _last_detailed_log_path = detailed_path

    updated_history = _append_assistant_message(
        updated_history,
        "✅ Фидбэк сгенерирован. Перейдите на вкладку «Фидбэк».",
    )

    yield (
        "✅ Интервью завершено",
        updated_history,
        feedback_text,
        str(summary_path),
        str(detailed_path),
        send_btn_disabled,
        msg_input_disabled,
    )


async def reset_interview() -> tuple[
    str,
    dict[str, Any],
    list[Any],
    str,
    None,
    None,
    dict[str, Any],
]:
    """
    Асинхронно сбрасывает текущее интервью.

    Закрывает активную сессию и очищает все данные интерфейса
    для начала нового интервью. Блокирует элементы ввода до
    старта нового интервью.

    :return: Tuple (статус, msg_input, пустая история, пустой фидбэк, None, None, send_btn).
    """
    global _current_session, _last_log_path, _last_detailed_log_path

    if _current_session is not None:
        await _current_session.close()
        _current_session = None

    _last_log_path = None
    _last_detailed_log_path = None

    return (
        "🔄 Сессия сброшена. Настройте параметры и начните новое интервью.",
        gr.update(value="", interactive=False),
        [],
        "",
        None,
        None,
        gr.update(interactive=False),
    )


def refresh_models() -> dict[str, Any]:
    """
    Обновляет список моделей из LiteLLM API.

    :return: Обновление компонента Dropdown со списком моделей.
    """
    models: list[str] = get_models_for_ui()
    default_value: str = settings.LITELLM_MODEL
    value: str = (
        default_value if default_value in models else (models[0] if models else "")
    )
    return gr.update(choices=models, value=value)


def create_gradio_interface() -> gr.Blocks:
    """
    Создаёт Gradio интерфейс приложения.

    :return: Объект Gradio Blocks с полностью настроенным интерфейсом.
    """
    initial_models: list[str] = get_models_for_ui()
    default_model: str = settings.LITELLM_MODEL
    initial_model_value: str = (
        default_model
        if default_model in initial_models
        else (initial_models[0] if initial_models else "")
    )

    with gr.Blocks(
        title="Multi-Agent Interview Coach",
        theme=gr.themes.Base(
            primary_hue=gr.themes.colors.indigo,
            secondary_hue=gr.themes.colors.purple,
            neutral_hue=gr.themes.colors.slate,
            font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"],
            font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "Consolas", "monospace"],
        ).set(
            body_background_fill="#0f1117",
            body_background_fill_dark="#0f1117",
            block_background_fill="transparent",
            block_background_fill_dark="transparent",
            block_border_color="rgba(99, 102, 241, 0.15)",
            block_border_color_dark="rgba(99, 102, 241, 0.15)",
            block_label_background_fill="transparent",
            block_label_background_fill_dark="transparent",
            block_label_text_color="#94a3b8",
            block_label_text_color_dark="#94a3b8",
            block_title_text_color="#e2e8f0",
            block_title_text_color_dark="#e2e8f0",
            input_background_fill="#24253a",
            input_background_fill_dark="#24253a",
            input_border_color="rgba(99, 102, 241, 0.15)",
            input_border_color_dark="rgba(99, 102, 241, 0.15)",
            background_fill_primary="#0f1117",
            background_fill_primary_dark="#0f1117",
            background_fill_secondary="transparent",
            background_fill_secondary_dark="transparent",
            panel_background_fill="transparent",
            panel_background_fill_dark="transparent",
            code_background_fill="#24253a",
            code_background_fill_dark="#24253a",
            checkbox_background_color="#24253a",
            checkbox_background_color_dark="#24253a",
            button_primary_background_fill="#6366f1",
            button_primary_background_fill_dark="#6366f1",
            button_primary_background_fill_hover="#4f46e5",
            button_primary_background_fill_hover_dark="#4f46e5",
            button_primary_text_color="white",
            button_primary_text_color_dark="white",
            button_secondary_background_fill="#2e3048",
            button_secondary_background_fill_dark="#2e3048",
            button_secondary_background_fill_hover="#24253a",
            button_secondary_background_fill_hover_dark="#24253a",
            button_secondary_text_color="#94a3b8",
            button_secondary_text_color_dark="#94a3b8",
            body_text_color="#e2e8f0",
            body_text_color_dark="#e2e8f0",
            body_text_color_subdued="#94a3b8",
            body_text_color_subdued_dark="#94a3b8",
            border_color_primary="rgba(99, 102, 241, 0.15)",
            border_color_primary_dark="rgba(99, 102, 241, 0.15)",
        ),
        css=MAIN_CSS,
    ) as app:
        # ── Header ──────────────────────────────────────────────────────
        gr.HTML(HEADER_HTML)

        # ── Main Layout ─────────────────────────────────────────────────
        with gr.Row(equal_height=False):
            # ── Left Column: Settings ────────────────────────────────────
            with gr.Column(scale=3, min_width=320):
                with gr.Group(elem_classes=["settings-panel"]):
                    gr.HTML('<div class="panel-title">⚙️ Настройки интервью</div>')

                    # Model selection
                    with gr.Accordion("🤖 Модель LLM", open=True):
                        with gr.Row():
                            model_dropdown = gr.Dropdown(
                                label="Модель",
                                choices=initial_models,
                                value=initial_model_value,
                                interactive=True,
                                elem_classes=["model-selector"],
                                scale=5,
                            )
                            refresh_btn = gr.Button(
                                "🔄",
                                variant="secondary",
                                scale=1,
                                min_width=42,
                                size="sm",
                                elem_classes=["btn-refresh"],
                            )

                        max_turns_slider = gr.Slider(
                            label="Макс. ходов интервью",
                            minimum=settings.UI_MAX_TURNS_MIN,
                            maximum=settings.UI_MAX_TURNS_MAX,
                            value=settings.MAX_TURNS,
                            step=settings.UI_MAX_TURNS_STEP,
                        )

                    # Job description
                    with gr.Accordion("📋 Описание вакансии", open=False):
                        job_description_input = gr.Textbox(
                            label="Описание позиции",
                            placeholder=(
                                "Опишите вакансию, требования к кандидату, "
                                "стек технологий, обязанности...\n\n"
                                "Если оставить пустым — интервью будет общим."
                            ),
                            lines=settings.UI_JOB_DESC_LINES,
                            max_lines=settings.UI_JOB_DESC_MAX_LINES,
                            elem_classes=["job-desc-input"],
                        )

                    # Agent settings
                    with gr.Accordion("🛠️ Параметры агентов", open=False):
                        gr.HTML(
                            '<p class="hint-text">'
                            "Температура: 0 — точный, 1+ — креативный. "
                            "Токены: максимум длины ответа агента."
                            "</p>"
                        )

                        with gr.Accordion("👁️ Observer", open=False):
                            with gr.Group(elem_classes=["agent-config-section"]):
                                obs_temp = gr.Slider(
                                    label="Температура",
                                    minimum=settings.UI_TEMPERATURE_MIN,
                                    maximum=settings.UI_TEMPERATURE_MAX,
                                    value=settings.UI_OBSERVER_DEFAULT_TEMP,
                                    step=settings.UI_TEMPERATURE_STEP,
                                )
                                obs_tokens = gr.Slider(
                                    label="Макс. токенов",
                                    minimum=settings.UI_TOKENS_MIN,
                                    maximum=settings.UI_TOKENS_MAX,
                                    value=settings.UI_OBSERVER_DEFAULT_TOKENS,
                                    step=settings.UI_TOKENS_STEP,
                                )

                        with gr.Accordion("🎤 Interviewer", open=False):
                            with gr.Group(elem_classes=["agent-config-section"]):
                                int_temp = gr.Slider(
                                    label="Температура",
                                    minimum=settings.UI_TEMPERATURE_MIN,
                                    maximum=settings.UI_TEMPERATURE_MAX,
                                    value=settings.UI_INTERVIEWER_DEFAULT_TEMP,
                                    step=settings.UI_TEMPERATURE_STEP,
                                )
                                int_tokens = gr.Slider(
                                    label="Макс. токенов",
                                    minimum=settings.UI_TOKENS_MIN,
                                    maximum=settings.UI_TOKENS_MAX,
                                    value=settings.UI_INTERVIEWER_DEFAULT_TOKENS,
                                    step=settings.UI_TOKENS_STEP,
                                )

                        with gr.Accordion("📊 Evaluator", open=False):
                            with gr.Group(elem_classes=["agent-config-section"]):
                                eval_temp = gr.Slider(
                                    label="Температура",
                                    minimum=settings.UI_TEMPERATURE_MIN,
                                    maximum=settings.UI_TEMPERATURE_MAX,
                                    value=settings.UI_EVALUATOR_DEFAULT_TEMP,
                                    step=settings.UI_TEMPERATURE_STEP,
                                )
                                eval_tokens = gr.Slider(
                                    label="Макс. токенов",
                                    minimum=settings.UI_EVAL_TOKENS_MIN,
                                    maximum=settings.UI_EVAL_TOKENS_MAX,
                                    value=settings.UI_EVALUATOR_DEFAULT_TOKENS,
                                    step=settings.UI_EVAL_TOKENS_STEP,
                                )

                    # Action buttons
                    gr.HTML('<hr class="section-divider">')

                    start_btn = gr.Button(
                        "🚀 Начать интервью",
                        variant="primary",
                        elem_classes=["btn-start"],
                    )

                    with gr.Row():
                        stop_btn = gr.Button(
                            "🛑 Завершить",
                            variant="stop",
                            elem_classes=["btn-stop"],
                            scale=1,
                        )
                        reset_btn = gr.Button(
                            "🔄 Сбросить",
                            variant="secondary",
                            elem_classes=["btn-reset"],
                            scale=1,
                        )

                    status_output = gr.Textbox(
                        label="Статус",
                        value="⏳ Настройте параметры и нажмите «Начать интервью»",
                        interactive=False,
                        elem_classes=["status-bar"],
                    )

            # ── Right Column: Chat + Feedback ────────────────────────────
            with gr.Column(scale=9, min_width=600):
                with gr.Tabs():
                    # Tab 1: Interview Chat
                    with gr.TabItem("💬 Интервью", id=0):
                        chatbot = gr.Chatbot(
                            label="Диалог с интервьюером",
                            height=settings.UI_CHAT_HEIGHT,
                            type="messages",
                            elem_classes=["chat-area"],
                            show_copy_button=True,
                            avatar_images=(None, None),
                            placeholder=(
                                "<center style='background: transparent !important;'>"
                                "<br><br>"
                                "<h3 style='color: #64748b; background: transparent !important;'>"
                                "Добро пожаловать!</h3>"
                                "<p style='color: #475569; font-size: 0.9rem; background: transparent !important;'>"
                                "Настройте параметры слева и нажмите "
                                "<strong>«Начать интервью»</strong> для начала."
                                "</p>"
                                "</center>"
                            ),
                        )

                        with gr.Row():
                            msg_input = gr.Textbox(
                                label="Ваш ответ",
                                placeholder="Введите ваш ответ и нажмите кнопку «Отправить»...",
                                lines=settings.UI_MSG_INPUT_LINES,
                                max_lines=settings.UI_MSG_INPUT_MAX_LINES,
                                scale=6,
                                interactive=False,
                                elem_classes=["input-area"],
                            )
                            send_btn = gr.Button(
                                "📤",
                                scale=1,
                                min_width=60,
                                interactive=False,
                                elem_classes=["btn-send"],
                            )

                    # Tab 2: Feedback
                    with gr.TabItem("📊 Фидбэк", id=1):
                        with gr.Group(elem_classes=["feedback-panel"]):
                            feedback_output = gr.Textbox(
                                label="Финальная оценка",
                                lines=settings.UI_FEEDBACK_LINES,
                                max_lines=settings.UI_FEEDBACK_MAX_LINES,
                                interactive=False,
                                show_copy_button=True,
                                placeholder="Фидбэк появится здесь после завершения интервью...",
                            )

                        with gr.Row(elem_classes=["download-section"]):
                            main_log_file = gr.File(
                                label="📄 Основной лог",
                                interactive=False,
                                scale=1,
                            )
                            detailed_log_file = gr.File(
                                label="📄 Детальный лог",
                                interactive=False,
                                scale=1,
                            )

        # ── Shared inputs for agent settings ─────────────────────────────
        settings_inputs: list[gr.components.Component] = [
            model_dropdown,
            max_turns_slider,
            job_description_input,
            obs_temp,
            obs_tokens,
            int_temp,
            int_tokens,
            eval_temp,
            eval_tokens,
        ]

        # Выходы для start_interview и reset_interview.
        all_outputs: list[gr.components.Component] = [
            status_output,
            msg_input,
            chatbot,
            feedback_output,
            main_log_file,
            detailed_log_file,
            send_btn,
        ]

        # Выходы для add_user_message (шаг 1).
        user_step_outputs: list[gr.components.Component] = [
            msg_input,
            chatbot,
            send_btn,
            status_output,
        ]

        # Выходы для bot_respond (шаг 2) и stop_interview.
        bot_step_outputs: list[gr.components.Component] = [
            status_output,
            chatbot,
            feedback_output,
            main_log_file,
            detailed_log_file,
            send_btn,
            msg_input,
        ]

        # ── Event Handlers ───────────────────────────────────────────────

        refresh_btn.click(
            fn=refresh_models,
            inputs=[],
            outputs=[model_dropdown],
        )

        # Двухшаговый старт:
        # 1) мгновенно меняем статус + блокируем ввод (queue=False),
        # 2) затем выполняем реальный старт с генерацией приветствия.
        start_btn.click(
            fn=start_interview_prepare,
            inputs=[],
            outputs=all_outputs,
            queue=False,
        ).then(
            fn=start_interview,
            inputs=settings_inputs,
            outputs=all_outputs,
            show_progress="hidden",
        )

        # Паттерн двухшаговой отправки сообщения:
        # Шаг 1 (queue=False, sync): мгновенно добавляет сообщение пользователя
        #   в чат, очищает и блокирует поле ввода и кнопку отправки,
        #   выставляет статус «Генерация ответа...».
        #   Если сообщение пустое — ничего не происходит (ввод не блокируется).
        # Шаг 2 (.then, async generator, show_progress="hidden"):
        #   Обрабатывает сообщение через LLM, отображает ответ.
        #   При завершении интервью — двухэтапный yield: сначала
        #   «Интервью завершено. Формирую фидбэк...», затем «Фидбэк сгенерирован...».
        #   По окончании разблокирует ввод (если интервью не завершено).
        send_btn.click(
            fn=add_user_message,
            inputs=[msg_input, chatbot],
            outputs=user_step_outputs,
            queue=False,
        ).then(
            fn=bot_respond,
            inputs=[chatbot],
            outputs=bot_step_outputs,
            show_progress="hidden",
        )

        msg_input.submit(
            fn=add_user_message,
            inputs=[msg_input, chatbot],
            outputs=user_step_outputs,
            queue=False,
        ).then(
            fn=bot_respond,
            inputs=[chatbot],
            outputs=bot_step_outputs,
            show_progress="hidden",
        )

        stop_btn.click(
            fn=stop_interview,
            inputs=[chatbot],
            outputs=bot_step_outputs,
            show_progress="hidden",
        )

        reset_btn.click(
            fn=reset_interview,
            inputs=[],
            outputs=all_outputs,
        )

    return app  # type: ignore[no-any-return]


def launch_app(
    server_name: str,
    server_port: int,
    share: bool,
) -> None:
    """
    Запускает Gradio приложение.

    :param server_name: Хост сервера.
    :param server_port: Порт сервера.
    :param share: Создать публичную ссылку.
    """
    setup_logging()
    logger.info(f"Launching Gradio app on {server_name}:{server_port}")

    app: gr.Blocks = create_gradio_interface()
    app.launch(server_name=server_name, server_port=server_port, share=share)
