"""
Логгер для сессии интервью.
"""

from __future__ import annotations

import json
import logging

from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.config import settings
from ..core.logger_setup import get_system_logger
from ..schemas.feedback import InterviewFeedback, InterviewLog
from ..schemas.interview import InterviewState

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


class InterviewLogger:
    """
    Логгер для сохранения сессии интервью.

    :ivar team_name: Название команды.
    :ivar log_dir: Директория для логов.
    """

    def __init__(self, team_name: str, log_dir: Path) -> None:
        self._team_name = team_name
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def save_session(
        self,
        state: InterviewState,
        feedback: InterviewFeedback | None = None,
    ) -> Path:
        """
        Сохраняет сессию интервью в JSON файл (формат по ТЗ).

        :param state: Состояние интервью.
        :param feedback: Финальный фидбэк (опционально).
        :return: Путь к сохранённому файлу.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"interview_log_{timestamp}.json"
        filepath = self._log_dir / filename

        log_data = InterviewLog(
            participant_name=state.participant_name,
            turns=[turn.to_log_dict() for turn in state.turns],
            final_feedback=feedback.to_formatted_string() if feedback else None,
        )

        with filepath.open("w", encoding="utf-8") as f:
            json.dump(log_data.model_dump(), f, ensure_ascii=False, indent=2)

        logger.info(f"Interview log saved: path={filepath}")
        return filepath

    def save_raw_log(
        self,
        state: InterviewState,
        feedback: InterviewFeedback | None = None,
    ) -> Path:
        """
        Сохраняет детальный лог с внутренними мыслями агентов.

        :param state: Состояние интервью.
        :param feedback: Финальный фидбэк (опционально).
        :return: Путь к файлу.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"interview_detailed_{timestamp}.json"
        filepath = self._log_dir / filename

        log_data: dict[str, Any] = {
            "participant_name": state.participant_name,
            "candidate_info": {
                "name": state.candidate.name,
                "position": state.candidate.position,
                "target_grade": state.candidate.target_grade.value
                if state.candidate.target_grade
                else None,
                "experience": state.candidate.experience,
                "technologies": state.candidate.technologies,
            },
            "interview_stats": {
                "total_turns": len(state.turns),
                "final_difficulty": state.current_difficulty.name,
                "confirmed_skills": state.confirmed_skills,
                "knowledge_gaps": state.knowledge_gaps,
                "covered_topics": state.covered_topics,
            },
            "turns": [turn.to_detailed_log_dict() for turn in state.turns],
            "final_feedback": feedback.model_dump() if feedback else None,
        }

        with filepath.open("w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2, default=str)

        logger.info(f"Detailed interview log saved: path={filepath}")
        return filepath


def create_interview_logger() -> InterviewLogger:
    """
    Создаёт экземпляр логгера интервью.

    :return: Экземпляр InterviewLogger.
    """
    return InterviewLogger(
        team_name=settings.TEAM_NAME,
        log_dir=settings.INTERVIEW_LOG_DIR,
    )
