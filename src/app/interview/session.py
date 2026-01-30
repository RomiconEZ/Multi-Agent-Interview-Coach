"""
Менеджер сессии интервью.

Координирует работу агентов и управляет состоянием интервью.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..agents import EvaluatorAgent, InterviewerAgent, ObserverAgent
from ..core.config import settings
from ..core.logger_setup import get_system_logger
from ..llm.client import LLMClient, create_llm_client
from ..schemas.feedback import InterviewFeedback
from ..schemas.interview import (
    AnswerQuality,
    CandidateInfo,
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

    @property
    def is_active(self) -> bool:
        """Проверяет, активна ли сессия."""
        return self._state is not None and self._state.is_active

    @property
    def state(self) -> InterviewState | None:
        """Возвращает текущее состояние."""
        return self._state

    async def start(self) -> str:
        """
        Начинает новую сессию интервью.

        :return: Приветственное сообщение.
        """
        self._state = InterviewState()

        logger.info("Starting new interview session")

        greeting = await self._interviewer.generate_greeting(self._state)
        self._last_agent_message = greeting

        turn = InterviewTurn(
            turn_id=1,
            agent_visible_message=greeting,
        )
        self._state.add_turn(turn)

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

        # Записываем ответ пользователя в предыдущий ход
        if self._state.turns:
            self._state.turns[-1].user_message = user_message

        logger.debug(f"Processing user message: {user_message[:50]}...")

        # Анализ ответа Observer'ом
        analysis = await self._observer.process(
            state=self._state,
            user_message=user_message,
            last_question=self._last_agent_message,
        )

        logger.debug(f"Observer analysis: type={analysis.response_type}, quality={analysis.quality}")

        # Извлечение информации о кандидате
        if analysis.extracted_info:
            self._update_candidate_info(analysis.extracted_info)

        # Проверка на команду остановки
        if analysis.response_type == ResponseType.STOP_COMMAND:
            self._state.is_active = False
            return "Завершаю интервью и формирую фидбэк...", True

        # Обновление состояния
        self._update_state_from_analysis(analysis, user_message)
        
        # Адаптивность: корректировка сложности с логированием
        old_difficulty = self._state.current_difficulty
        self._state.adjust_difficulty(analysis)
        if old_difficulty != self._state.current_difficulty:
            logger.info(
                f"ADAPTIVITY: Difficulty changed from {old_difficulty.name} to "
                f"{self._state.current_difficulty.name} "
                f"(good_streak={self._state.consecutive_good_answers}, "
                f"bad_streak={self._state.consecutive_bad_answers})"
            )
        
        # Если Observer определил demonstrated_level выше/ниже заявленного
        if analysis.demonstrated_level and self._state.candidate.target_grade:
            logger.info(
                f"ADAPTIVITY: Candidate claimed {self._state.candidate.target_grade.value}, "
                f"demonstrated {analysis.demonstrated_level}"
            )

        # Генерация ответа Interviewer'ом
        response, thoughts = await self._interviewer.process(
            state=self._state,
            analysis=analysis,
            user_message=user_message,
        )

        self._last_agent_message = response

        # Записываем thoughts в предыдущий turn и создаём новый
        if self._state.turns:
            self._state.turns[-1].internal_thoughts = thoughts

        turn = InterviewTurn(
            turn_id=self._state.current_turn + 1,
            agent_visible_message=response,
        )
        self._state.add_turn(turn)

        # Проверка лимита ходов
        if self._state.current_turn >= self._max_turns:
            self._state.is_active = False
            return response + "\n\n[Достигнут лимит вопросов. Формирую фидбэк...]", True

        return response, False

    async def generate_feedback(self) -> tuple[InterviewFeedback, Path, Path]:
        """
        Генерирует финальный фидбэк и сохраняет логи.

        :return: Tuple (фидбэк, путь к основному логу, путь к детальному логу).
        """
        if self._state is None:
            raise ValueError("Interview session not started")

        logger.info("Generating final feedback")

        feedback = await self._evaluator.process(self._state)

        summary_path = self._interview_logger.save_session(self._state, feedback)
        detailed_path = self._interview_logger.save_raw_log(self._state, feedback)

        return feedback, summary_path, detailed_path

    def _update_candidate_info(self, extracted: Any) -> None:
        """Обновляет информацию о кандидате из extracted_info."""
        if self._state is None:
            return

        if extracted.name and not self._state.candidate.name:
            self._state.candidate.name = extracted.name
            self._state.participant_name = extracted.name
            logger.info(f"Extracted candidate name: {extracted.name}")

        if extracted.position and not self._state.candidate.position:
            self._state.candidate.position = extracted.position
            logger.info(f"Extracted position: {extracted.position}")

        if extracted.grade and not self._state.candidate.target_grade:
            grade = self._parse_grade(extracted.grade)
            self._state.candidate.target_grade = grade
            self._state.current_difficulty = self._get_initial_difficulty(grade)
            logger.info(f"Extracted grade: {grade.value}, setting difficulty to {self._state.current_difficulty.name}")

        if extracted.experience and not self._state.candidate.experience:
            self._state.candidate.experience = extracted.experience
            logger.info(f"Extracted experience: {extracted.experience[:50]}...")

        # Обновление технологий (добавляем к существующим)
        if extracted.technologies:
            for tech in extracted.technologies:
                if tech and tech not in self._state.candidate.technologies:
                    self._state.candidate.technologies.append(tech)
            logger.info(f"Extracted technologies: {self._state.candidate.technologies}")

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
                "topic": ", ".join(analysis.detected_topics) if analysis.detected_topics else "Общие знания",
                "user_answer": user_message[:200],
                "correct_answer": analysis.correct_answer,
            }
            self._state.knowledge_gaps.append(gap)

    async def close(self) -> None:
        """Закрывает сессию и освобождает ресурсы."""
        await self._llm_client.close()
        logger.info("Interview session closed")


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
