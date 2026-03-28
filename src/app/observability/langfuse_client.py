"""
Клиент для интеграции с Langfuse (self-hosted / локальный).

Предоставляет трекинг LLM вызовов и сессий интервью с метриками по токенам и стоимости.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langfuse import Langfuse
from langfuse.client import StatefulGenerationClient, StatefulTraceClient

from ..core.config import settings
from ..core.logger_setup import get_system_logger

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


@dataclass
class TokenUsage:
    """Статистика использования токенов и стоимости."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        """Добавляет токены и стоимость к статистике."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += input_tokens + output_tokens
        self.cost_usd += cost_usd

    def to_dict(self) -> dict[str, int | float]:
        """Преобразует в словарь."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


@dataclass
class SessionMetrics:
    """
    Метрики сессии интервью.

    Собирает статистику по токенам и стоимости для всего диалога и по агентам.
    """

    total_usage: TokenUsage = field(default_factory=TokenUsage)
    generation_count: int = 0
    turn_count: int = 0

    # Метрики по агентам
    observer_usage: TokenUsage = field(default_factory=TokenUsage)
    observer_calls: int = 0

    interviewer_usage: TokenUsage = field(default_factory=TokenUsage)
    interviewer_calls: int = 0

    evaluator_usage: TokenUsage = field(default_factory=TokenUsage)
    evaluator_calls: int = 0

    def add_generation(
        self,
        generation_name: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """
        Добавляет метрики генерации.

        :param generation_name: Имя генерации (для определения агента).
        :param input_tokens: Входные токены.
        :param output_tokens: Выходные токены.
        :param cost_usd: Стоимость вызова в USD.
        """
        self.total_usage.add(input_tokens, output_tokens, cost_usd)
        self.generation_count += 1

        name_lower = generation_name.lower()
        if "observer" in name_lower:
            self.observer_usage.add(input_tokens, output_tokens, cost_usd)
            self.observer_calls += 1
        elif "interviewer" in name_lower:
            self.interviewer_usage.add(input_tokens, output_tokens, cost_usd)
            self.interviewer_calls += 1
        elif "evaluator" in name_lower:
            self.evaluator_usage.add(input_tokens, output_tokens, cost_usd)
            self.evaluator_calls += 1

    def increment_turn(self) -> None:
        """Увеличивает счётчик ходов."""
        self.turn_count += 1

    def get_average_tokens_per_turn(self) -> float:
        """Возвращает среднее количество токенов на ход."""
        if self.turn_count == 0:
            return 0.0
        return self.total_usage.total_tokens / self.turn_count

    def get_average_tokens_per_generation(self) -> float:
        """Возвращает среднее количество токенов на генерацию."""
        if self.generation_count == 0:
            return 0.0
        return self.total_usage.total_tokens / self.generation_count

    def get_total_cost(self) -> float:
        """Возвращает общую стоимость сессии в USD."""
        return self.total_usage.cost_usd

    def get_cost_per_turn(self) -> float:
        """Возвращает среднюю стоимость одного хода в USD."""
        if self.turn_count == 0:
            return 0.0
        return self.total_usage.cost_usd / self.turn_count

    def to_dict(self) -> dict[str, Any]:
        """Преобразует в словарь для логирования/отправки в Langfuse."""
        return {
            "total": self.total_usage.to_dict(),
            "generation_count": self.generation_count,
            "turn_count": self.turn_count,
            "avg_tokens_per_turn": round(self.get_average_tokens_per_turn(), 2),
            "avg_tokens_per_generation": round(
                self.get_average_tokens_per_generation(), 2
            ),
            "total_cost_usd": round(self.get_total_cost(), 6),
            "cost_per_turn_usd": round(self.get_cost_per_turn(), 6),
            "by_agent": {
                "observer": {
                    **self.observer_usage.to_dict(),
                    "calls": self.observer_calls,
                },
                "interviewer": {
                    **self.interviewer_usage.to_dict(),
                    "calls": self.interviewer_calls,
                },
                "evaluator": {
                    **self.evaluator_usage.to_dict(),
                    "calls": self.evaluator_calls,
                },
            },
        }

    def to_summary_string(self) -> str:
        """Возвращает читаемую строку с метриками."""
        lines = [
            "=" * 50,
            "📊 МЕТРИКИ СЕССИИ (ТОКЕНЫ)",
            "=" * 50,
            f"Всего токенов: {self.total_usage.total_tokens:,}",
            f"  - Входные: {self.total_usage.input_tokens:,}",
            f"  - Выходные: {self.total_usage.output_tokens:,}",
            "",
            f"Количество ходов: {self.turn_count}",
            f"Количество LLM вызовов: {self.generation_count}",
            f"Среднее токенов на ход: {self.get_average_tokens_per_turn():,.1f}",
            f"Среднее токенов на вызов: {self.get_average_tokens_per_generation():,.1f}",
            "",
            "По агентам:",
            f"  Observer: {self.observer_usage.total_tokens:,} токенов ({self.observer_calls} вызовов)",
            f"  Interviewer: {self.interviewer_usage.total_tokens:,} токенов ({self.interviewer_calls} вызовов)",
            f"  Evaluator: {self.evaluator_usage.total_tokens:,} токенов ({self.evaluator_calls} вызовов)",
            "",
            "💰 СТОИМОСТЬ СЕССИИ",
            "-" * 50,
            f"Общая стоимость: ${self.get_total_cost():.6f}",
            f"Стоимость за ход: ${self.get_cost_per_turn():.6f}",
            f"  Observer: ${self.observer_usage.cost_usd:.6f}",
            f"  Interviewer: ${self.interviewer_usage.cost_usd:.6f}",
            f"  Evaluator: ${self.evaluator_usage.cost_usd:.6f}",
            "=" * 50,
        ]
        return "\n".join(lines)


class LangfuseTracker:
    """
    Трекер для Langfuse observability (self-hosted / локальный).

    Управляет трейсами и генерациями LLM вызовов с метриками по токенам и стоимости.
    """

    def __init__(
        self,
        public_key: str,
        secret_key: str,
        host: str,
        enabled: bool,
    ) -> None:
        self._enabled = enabled
        self._client: Langfuse | None = None
        self._session_metrics: dict[str, SessionMetrics] = {}

        if self._enabled:
            if not public_key or not secret_key:
                logger.warning(
                    "Langfuse enabled but keys not set. "
                    "Create API keys in Langfuse UI: Settings -> API Keys"
                )
                self._enabled = False
            else:
                try:
                    self._client = Langfuse(
                        public_key=public_key,
                        secret_key=secret_key,
                        host=host,
                    )
                    logger.info(f"Langfuse tracker initialized, host={host}")
                except Exception as e:
                    logger.error(f"Failed to initialize Langfuse: {e}")
                    self._enabled = False
        else:
            logger.info("Langfuse tracker disabled")

    @property
    def is_enabled(self) -> bool:
        """Проверяет, включён ли трекинг."""
        return self._enabled and self._client is not None

    def create_trace(
        self,
        name: str,
        session_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StatefulTraceClient | None:
        """
        Создаёт новый трейс.

        :param name: Имя трейса.
        :param session_id: ID сессии (для группировки).
        :param user_id: ID пользователя.
        :param metadata: Дополнительные метаданные.
        :return: Объект трейса или None если отключено.
        """
        if not self.is_enabled:
            return None

        if session_id:
            self._session_metrics[session_id] = SessionMetrics()

        try:
            trace = self._client.trace(
                name=name,
                session_id=session_id,
                user_id=user_id,
                metadata=metadata or {},
            )
            logger.debug(
                f"Langfuse trace created: name={name}, session_id={session_id}"
            )
            return trace
        except Exception as e:
            logger.error(f"Failed to create trace: {e}")
            return None

    def get_session_metrics(self, session_id: str) -> SessionMetrics | None:
        """
        Возвращает метрики сессии.

        :param session_id: ID сессии.
        :return: Метрики или None.
        """
        return self._session_metrics.get(session_id)

    def increment_turn(self, session_id: str) -> None:
        """
        Увеличивает счётчик ходов сессии.

        :param session_id: ID сессии.
        """
        metrics = self._session_metrics.get(session_id)
        if metrics:
            metrics.increment_turn()

    def create_generation(
        self,
        trace: StatefulTraceClient | None,
        name: str,
        model: str,
        input_messages: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
    ) -> StatefulGenerationClient | None:
        """
        Создаёт generation для LLM вызова.

        :param trace: Родительский трейс.
        :param name: Имя генерации.
        :param model: Имя модели.
        :param input_messages: Входные сообщения.
        :param metadata: Дополнительные метаданные.
        :return: Объект генерации или None.
        """
        if not self.is_enabled or trace is None:
            return None

        try:
            generation = trace.generation(
                name=name,
                model=model,
                input=input_messages,
                metadata=metadata or {},
            )
            logger.debug(f"Langfuse generation created: name={name}, model={model}")
            return generation
        except Exception as e:
            logger.error(f"Failed to create generation: {e}")
            return None

    def end_generation(
        self,
        generation: StatefulGenerationClient | None,
        output: str,
        cost_usd: float,
        usage: dict[str, int] | None = None,
        level: str = "DEFAULT",
        status_message: str | None = None,
        session_id: str | None = None,
        generation_name: str | None = None,
    ) -> None:
        """
        Завершает generation с результатом.

        :param generation: Объект генерации.
        :param output: Выходной текст.
        :param cost_usd: Стоимость вызова в USD (из LiteLLM proxy).
        :param usage: Статистика использования токенов.
        :param level: Уровень (DEFAULT, DEBUG, WARNING, ERROR).
        :param status_message: Сообщение о статусе.
        :param session_id: ID сессии для метрик.
        :param generation_name: Имя генерации для метрик.
        """
        if generation is not None:
            try:
                generation.end(
                    output=output,
                    usage=usage,
                    level=level,
                    status_message=status_message,
                )
            except Exception as e:
                logger.error(f"Failed to end generation: {e}")

        # Обновляем метрики сессии независимо от статуса generation
        if session_id and generation_name and usage:
            metrics = self._session_metrics.get(session_id)
            if metrics:
                metrics.add_generation(
                    generation_name=generation_name,
                    input_tokens=usage.get("input", 0),
                    output_tokens=usage.get("output", 0),
                    cost_usd=cost_usd,
                )

        logger.debug(
            f"Langfuse generation ended: output_len={len(output)}, "
            f"usage={usage}, cost_usd={cost_usd:.6f}"
        )

    def end_generation_with_error(
        self,
        generation: StatefulGenerationClient | None,
        error: str,
    ) -> None:
        """
        Завершает generation с ошибкой.

        :param generation: Объект генерации.
        :param error: Текст ошибки.
        """
        if generation is None:
            return

        try:
            generation.end(
                output=None,
                level="ERROR",
                status_message=error,
            )
            logger.debug(f"Langfuse generation ended with error: {error}")
        except Exception as e:
            logger.error(f"Failed to end generation with error: {e}")

    def add_span(
        self,
        trace: StatefulTraceClient | None,
        name: str,
        input_data: Any = None,
        output_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Добавляет span к трейсу.

        :param trace: Родительский трейс.
        :param name: Имя спана.
        :param input_data: Входные данные.
        :param output_data: Выходные данные.
        :param metadata: Метаданные.
        """
        if not self.is_enabled or trace is None:
            return

        try:
            trace.span(
                name=name,
                input=input_data,
                output=output_data,
                metadata=metadata or {},
            )
            logger.debug(f"Langfuse span added: name={name}")
        except Exception as e:
            logger.error(f"Failed to add span: {e}")

    def score_trace(
        self,
        trace: StatefulTraceClient | None,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        """
        Добавляет оценку к трейсу.

        :param trace: Трейс.
        :param name: Имя метрики.
        :param value: Значение.
        :param comment: Комментарий.
        """
        if not self.is_enabled or trace is None:
            return

        try:
            trace.score(
                name=name,
                value=value,
                comment=comment,
            )
            logger.debug(f"Langfuse score added: name={name}, value={value}")
        except Exception as e:
            logger.error(f"Failed to add score: {e}")

    def add_session_metrics_to_trace(
        self,
        trace: StatefulTraceClient | None,
        session_id: str,
    ) -> None:
        """
        Добавляет финальные метрики сессии к трейсу.

        :param trace: Трейс.
        :param session_id: ID сессии.
        """
        if not self.is_enabled or trace is None:
            return

        metrics = self._session_metrics.get(session_id)
        if metrics is None:
            return

        # Добавляем span с полными метриками
        self.add_span(
            trace=trace,
            name="session_token_metrics",
            output_data=metrics.to_dict(),
            metadata={"type": "final_metrics"},
        )

        # Добавляем отдельные score для ключевых метрик
        self.score_trace(
            trace=trace,
            name="total_tokens",
            value=float(metrics.total_usage.total_tokens),
            comment=f"input={metrics.total_usage.input_tokens}, output={metrics.total_usage.output_tokens}",
        )

        self.score_trace(
            trace=trace,
            name="total_turns",
            value=float(metrics.turn_count),
            comment="Number of conversation turns",
        )

        self.score_trace(
            trace=trace,
            name="llm_calls",
            value=float(metrics.generation_count),
            comment="Number of LLM API calls",
        )

        self.score_trace(
            trace=trace,
            name="avg_tokens_per_turn",
            value=metrics.get_average_tokens_per_turn(),
            comment="Average tokens consumed per conversation turn",
        )

        # Метрика стоимости сессии
        total_cost: float = metrics.get_total_cost()
        self.score_trace(
            trace=trace,
            name="session_cost_usd",
            value=total_cost,
            comment=(
                f"Total session cost: ${total_cost:.6f}, "
                f"cost per turn: ${metrics.get_cost_per_turn():.6f}"
            ),
        )

        logger.info(
            f"Session metrics added: session_id={session_id}, "
            f"total_tokens={metrics.total_usage.total_tokens}, "
            f"turns={metrics.turn_count}, "
            f"generations={metrics.generation_count}, "
            f"cost_usd=${total_cost:.6f}"
        )

    def flush(self) -> None:
        """Отправляет все накопленные данные."""
        if self._client is not None:
            try:
                self._client.flush()
                logger.debug("Langfuse data flushed")
            except Exception as e:
                logger.error(f"Failed to flush Langfuse data: {e}")

    def shutdown(self) -> None:
        """Корректно завершает работу клиента."""
        if self._client is not None:
            try:
                self._client.shutdown()
                logger.info("Langfuse tracker shutdown")
            except Exception as e:
                logger.error(f"Error during Langfuse shutdown: {e}")

    def clear_session_metrics(self, session_id: str) -> None:
        """
        Очищает метрики сессии.

        :param session_id: ID сессии.
        """
        if session_id in self._session_metrics:
            del self._session_metrics[session_id]


_tracker_instance: LangfuseTracker | None = None


def get_langfuse_tracker() -> LangfuseTracker:
    """
    Возвращает singleton экземпляр LangfuseTracker.

    :return: Экземпляр LangfuseTracker.
    """
    global _tracker_instance

    if _tracker_instance is None:
        _tracker_instance = LangfuseTracker(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
            enabled=settings.LANGFUSE_ENABLED,
        )

    return _tracker_instance
