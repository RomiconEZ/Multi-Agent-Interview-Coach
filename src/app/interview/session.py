"""
Менеджер сессии интервью.

Координирует работу агентов и управляет состоянием интервью.
"""

from __future__ import annotations

import logging

from pathlib import Path
from typing import Any
from uuid import uuid4

from langfuse.client import StatefulTraceClient

from ..agents import EvaluatorAgent, InterviewerAgent, ObserverAgent
from ..core.config import settings
from ..core.logger_setup import get_system_logger
from ..llm.client import LLMClient, create_llm_client
from ..observability import SessionMetrics, get_langfuse_tracker
from ..schemas.feedback import InterviewFeedback
from ..schemas.interview import (
    AnswerQuality,
    DifficultyLevel,
    GradeLevel,
    InterviewState,
    InterviewTurn,
    ResponseType,
)
from .logger import InterviewLogger, create_interview_logger

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


class InterviewSession:
    """
    Менеджер сессии интервью.

    Координирует Observer, Interviewer и Evaluator агентов.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        interview_logger: InterviewLogger,
        max_turns: int,
    ) -> None:
        self._llm_client = llm_client
        self._interview_logger = interview_logger
        self._max_turns = max_turns

        self._observer = ObserverAgent(llm_client)
        self._interviewer = InterviewerAgent(llm_client)
        self._evaluator = EvaluatorAgent(llm_client)

        self._state: InterviewState | None = None
        self._last_agent_message: str = ""

        self._langfuse = get_langfuse_tracker()
        self._trace: StatefulTraceClient | None = None
        self._session_id: str = ""

    @property
    def is_active(self) -> bool:
        """Проверяет, активна ли сессия."""
        return self._state is not None and self._state.is_active

    @property
    def state(self) -> InterviewState | None:
        """Возвращает текущее состояние."""
        return self._state

    def get_session_metrics(self) -> SessionMetrics | None:
        """
        Возвращает метрики текущей сессии.

        :return: Метрики или None.
        """
        if not self._session_id:
            return None
        return self._langfuse.get_session_metrics(self._session_id)

    async def start(self) -> str:
        """
        Начинает новую сессию интервью.

        :return: Приветственное сообщение.
        """
        self._state = InterviewState()
        self._session_id = str(uuid4())

        self._trace = self._langfuse.create_trace(
            name="interview_session",
            session_id=self._session_id,
            metadata={
                "model": self._llm_client.model,
                "max_turns": self._max_turns,
            },
        )
        self._llm_client.set_trace(self._trace, self._session_id)

        logger.info(f"Starting new interview session, session_id={self._session_id}")

        greeting = await self._interviewer.generate_greeting(self._state)
        self._last_agent_message = greeting

        turn = InterviewTurn(
            turn_id=1,
            agent_visible_message=greeting,
        )
        self._state.add_turn(turn)

        self._langfuse.add_span(
            trace=self._trace,
            name="greeting",
            output_data=greeting,
        )

        return greeting

    async def process_message(self, user_message: str) -> tuple[str, bool]:
        """
        Обрабатывает сообщение пользователя.

        :param user_message: Сообщение кандидата.
        :return: Tuple (ответ агента, завершено ли интервью).
        """
        if self._state is None:
            raise ValueError("Interview session not started")

        if not self._state.is_active:
            return "Интервью завершено.", True

        if self._state.turns:
            self._state.turns[-1].user_message = user_message

        logger.debug(f"Processing user message: {user_message[:50]}...")

        # Увеличиваем счётчик ходов для метрик
        self._langfuse.increment_turn(self._session_id)

        self._langfuse.add_span(
            trace=self._trace,
            name="user_message",
            input_data=user_message,
            metadata={"turn": self._state.current_turn},
        )

        analysis = await self._observer.process(
            state=self._state,
            user_message=user_message,
            last_question=self._last_agent_message,
        )

        logger.debug(
            f"Observer analysis: type={analysis.response_type}, quality={analysis.quality}"
        )

        self._langfuse.add_span(
            trace=self._trace,
            name="observer_analysis",
            output_data={
                "response_type": analysis.response_type.value,
                "quality": analysis.quality.value,
                "is_factually_correct": analysis.is_factually_correct,
                "recommendation": analysis.recommendation,
            },
        )

        if analysis.extracted_info:
            self._update_candidate_info(analysis.extracted_info)

        if analysis.response_type == ResponseType.STOP_COMMAND:
            if self._state.turns:
                self._state.turns[-1].internal_thoughts = list(analysis.thoughts)
            self._state.is_active = False
            return "Завершаю интервью и формирую фидбэк...", True

        self._update_state_from_analysis(analysis, user_message)

        self._apply_difficulty_adjustment(analysis)

        if analysis.demonstrated_level and self._state.candidate.target_grade:
            logger.info(
                f"ADAPTIVITY: Candidate claimed {self._state.candidate.target_grade.value}, "
                f"demonstrated {analysis.demonstrated_level}"
            )

        response, thoughts = await self._interviewer.process(
            state=self._state,
            analysis=analysis,
            user_message=user_message,
        )

        self._last_agent_message = response

        if self._state.turns:
            self._state.turns[-1].internal_thoughts = thoughts

        turn = InterviewTurn(
            turn_id=self._state.current_turn + 1,
            agent_visible_message=response,
        )
        self._state.add_turn(turn)

        self._langfuse.add_span(
            trace=self._trace,
            name="interviewer_response",
            output_data=response,
            metadata={"turn": self._state.current_turn},
        )

        if self._state.current_turn >= self._max_turns:
            self._state.is_active = False
            return response + "\n\n[Достигнут лимит вопросов. Формирую фидбэк...]", True

        return response, False

    def _apply_difficulty_adjustment(self, analysis: Any) -> None:
        """
        Применяет корректировку сложности с детальным логированием.

        :param analysis: Анализ от Observer.
        """
        if self._state is None:
            return

        old_difficulty = self._state.current_difficulty
        old_good_streak = self._state.consecutive_good_answers
        old_bad_streak = self._state.consecutive_bad_answers

        self._state.adjust_difficulty(analysis)

        if old_difficulty != self._state.current_difficulty:
            logger.info(
                f"ADAPTIVITY: Difficulty changed from {old_difficulty.name} to "
                f"{self._state.current_difficulty.name} "
                f"(good_streak: {old_good_streak}->{self._state.consecutive_good_answers}, "
                f"bad_streak: {old_bad_streak}->{self._state.consecutive_bad_answers})"
            )

            self._langfuse.add_span(
                trace=self._trace,
                name="difficulty_change",
                metadata={
                    "from": old_difficulty.name,
                    "to": self._state.current_difficulty.name,
                },
            )
        else:
            logger.debug(
                f"ADAPTIVITY: Difficulty unchanged at {self._state.current_difficulty.name} "
                f"(should_increase={analysis.should_increase_difficulty}, "
                f"should_simplify={analysis.should_simplify}, "
                f"good_streak: {old_good_streak}->{self._state.consecutive_good_answers}, "
                f"bad_streak: {old_bad_streak}->{self._state.consecutive_bad_answers})"
            )

    async def generate_feedback(self) -> tuple[InterviewFeedback, Path, Path]:
        """
        Генерирует финальный фидбэк и сохраняет логи.

        :return: Tuple (фидбэк, путь к основному логу, путь к детальному логу).
        """
        if self._state is None:
            raise ValueError("Interview session not started")

        logger.info("Generating final feedback")

        feedback = await self._evaluator.process(self._state)

        self._langfuse.add_span(
            trace=self._trace,
            name="final_feedback",
            output_data={
                "grade": feedback.verdict.grade.value,
                "hiring_recommendation": feedback.verdict.hiring_recommendation.value,
                "confidence_score": feedback.verdict.confidence_score,
            },
        )

        self._langfuse.score_trace(
            trace=self._trace,
            name="confidence_score",
            value=feedback.verdict.confidence_score / 100.0,
            comment=f"Grade: {feedback.verdict.grade.value}, Recommendation: {feedback.verdict.hiring_recommendation.value}",
        )

        # Добавляем финальные метрики сессии в Langfuse
        self._langfuse.add_session_metrics_to_trace(self._trace, self._session_id)

        # Логируем метрики в консоль
        metrics = self.get_session_metrics()
        if metrics:
            logger.info(f"\n{metrics.to_summary_string()}")

        self._langfuse.flush()

        summary_path = self._interview_logger.save_session(self._state, feedback)
        detailed_path = self._interview_logger.save_raw_log(self._state, feedback)

        # Сохраняем метрики в детальный лог (добавим отдельно)
        if metrics:
            self._save_metrics_to_log(metrics, detailed_path)

        return feedback, summary_path, detailed_path

    def _save_metrics_to_log(self, metrics: SessionMetrics, log_path: Path) -> None:
        """
        Добавляет метрики токенов в детальный лог.

        :param metrics: Метрики сессии.
        :param log_path: Путь к файлу лога.
        """
        import json

        try:
            with log_path.open("r", encoding="utf-8") as f:
                log_data = json.load(f)

            log_data["token_metrics"] = metrics.to_dict()

            with log_path.open("w", encoding="utf-8") as f:
                json.dump(log_data, f, ensure_ascii=False, indent=2)

            logger.info(f"Token metrics added to log: {log_path}")
        except Exception as e:
            logger.error(f"Failed to save metrics to log: {e}")

    def _update_candidate_info(self, extracted: Any) -> None:
        """Обновляет информацию о кандидате из extracted_info."""
        if self._state is None:
            return

        if extracted.name and not self._state.candidate.name:
            self._state.candidate.name = extracted.name
            self._state.participant_name = extracted.name
            logger.info(f"Extracted candidate name: {extracted.name}")

            if self._trace is not None:
                self._trace.update(user_id=extracted.name)

        if extracted.position and not self._state.candidate.position:
            self._state.candidate.position = extracted.position
            logger.info(f"Extracted position: {extracted.position}")

        if extracted.grade and not self._state.candidate.target_grade:
            grade = self._parse_grade(extracted.grade)
            self._state.candidate.target_grade = grade
            self._state.current_difficulty = self._get_initial_difficulty(grade)
            logger.info(
                f"Extracted grade: {grade.value}, "
                f"setting difficulty to {self._state.current_difficulty.name}"
            )

        if extracted.experience and not self._state.candidate.experience:
            self._state.candidate.experience = extracted.experience
            logger.info(f"Extracted experience: {extracted.experience[:50]}...")

        if extracted.technologies:
            for tech in extracted.technologies:
                if tech and tech not in self._state.candidate.technologies:
                    self._state.candidate.technologies.append(tech)
            logger.info(f"Extracted technologies: {self._state.candidate.technologies}")

        self._langfuse.add_span(
            trace=self._trace,
            name="candidate_info_update",
            output_data={
                "name": self._state.candidate.name,
                "position": self._state.candidate.position,
                "grade": self._state.candidate.target_grade.value
                if self._state.candidate.target_grade
                else None,
                "technologies": self._state.candidate.technologies,
            },
        )

    def _parse_grade(self, grade_str: str) -> GradeLevel:
        """Парсит строку грейда."""
        mapping = {
            "intern": GradeLevel.INTERN,
            "junior": GradeLevel.JUNIOR,
            "middle": GradeLevel.MIDDLE,
            "senior": GradeLevel.SENIOR,
            "lead": GradeLevel.LEAD,
        }
        return mapping.get(grade_str.lower(), GradeLevel.JUNIOR)

    def _get_initial_difficulty(self, grade: GradeLevel) -> DifficultyLevel:
        """Определяет начальную сложность по грейду."""
        mapping = {
            GradeLevel.INTERN: DifficultyLevel.BASIC,
            GradeLevel.JUNIOR: DifficultyLevel.BASIC,
            GradeLevel.MIDDLE: DifficultyLevel.INTERMEDIATE,
            GradeLevel.SENIOR: DifficultyLevel.ADVANCED,
            GradeLevel.LEAD: DifficultyLevel.EXPERT,
        }
        return mapping.get(grade, DifficultyLevel.BASIC)

    def _update_state_from_analysis(
        self,
        analysis: Any,
        user_message: str,
    ) -> None:
        """Обновляет состояние на основе анализа."""
        if self._state is None:
            return

        for topic in analysis.detected_topics:
            if topic not in self._state.covered_topics:
                self._state.covered_topics.append(topic)

        if analysis.quality in (AnswerQuality.EXCELLENT, AnswerQuality.GOOD):
            if analysis.is_factually_correct:
                for topic in analysis.detected_topics:
                    if topic not in self._state.confirmed_skills:
                        self._state.confirmed_skills.append(topic)

        if not analysis.is_factually_correct or analysis.quality == AnswerQuality.WRONG:
            gap = {
                "topic": (
                    ", ".join(analysis.detected_topics)
                    if analysis.detected_topics
                    else "Общие знания"
                ),
                "user_answer": user_message[:200],
                "correct_answer": analysis.correct_answer,
            }
            self._state.knowledge_gaps.append(gap)

    async def close(self) -> None:
        """Закрывает сессию и освобождает ресурсы."""
        self._langfuse.flush()
        await self._llm_client.close()
        logger.info(f"Interview session closed, session_id={self._session_id}")


async def create_interview_session(model: str | None = None) -> InterviewSession:
    """
    Создаёт новую сессию интервью.

    :param model: Имя модели LLM (по умолчанию из конфигурации).
    :return: Экземпляр InterviewSession.
    """
    llm_client = create_llm_client(model)
    interview_logger = create_interview_logger()

    return InterviewSession(
        llm_client=llm_client,
        interview_logger=interview_logger,
        max_turns=settings.MAX_TURNS,
    )
