"""
Схемы данных для интервью-сессии.

Содержит модели для кандидата, сообщений, мыслей агентов и состояния интервью.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GradeLevel(str, Enum):
    """Уровень кандидата."""

    INTERN = "Intern"
    JUNIOR = "Junior"
    MIDDLE = "Middle"
    SENIOR = "Senior"
    LEAD = "Lead"


class CandidateInfo(BaseModel):
    """
    Информация о кандидате (извлекается из диалога).

    :ivar name: Имя кандидата (извлекается из первого ответа).
    :ivar position: Желаемая позиция.
    :ivar target_grade: Целевой грейд.
    :ivar experience: Описание опыта.
    :ivar technologies: Список технологий из опыта кандидата.
    """

    name: str | None = None
    position: str | None = None
    target_grade: GradeLevel | None = None
    experience: str | None = None
    technologies: list[str] = Field(default_factory=list)

    @field_validator("name", "position", "experience", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() if v else None


class InternalThought(BaseModel):
    """
    Внутренняя мысль агента.

    :ivar from_agent: Агент-источник мысли.
    :ivar to_agent: Агент-получатель.
    :ivar content: Содержание мысли.
    :ivar timestamp: Время создания.
    """

    from_agent: str
    to_agent: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_log_dict(self) -> dict[str, str]:
        """Преобразует в словарь для лога."""
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "content": self.content,
        }


class ResponseType(str, Enum):
    """Тип ответа пользователя."""

    NORMAL = "normal"
    HALLUCINATION = "hallucination"
    OFF_TOPIC = "off_topic"
    QUESTION = "question"
    STOP_COMMAND = "stop_command"
    INTRODUCTION = "introduction"
    INCOMPLETE = "incomplete"
    EXCELLENT = "excellent"


class AnswerQuality(str, Enum):
    """Качество ответа."""

    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"
    WRONG = "wrong"


class ExtractedCandidateInfo(BaseModel):
    """Информация о кандидате, извлечённая из ответа."""

    name: str | None = None
    position: str | None = None
    grade: str | None = None
    experience: str | None = None
    technologies: list[str] = Field(default_factory=list)


class ObserverAnalysis(BaseModel):
    """
    Результат анализа ответа наблюдателем.

    :ivar response_type: Тип ответа.
    :ivar quality: Качество ответа.
    :ivar is_factually_correct: Фактическая корректность.
    :ivar detected_topics: Обнаруженные темы.
    :ivar recommendation: Рекомендация для интервьюера.
    :ivar thoughts: Мысли наблюдателя.
    :ivar should_simplify: Нужно ли упростить вопросы.
    :ivar should_increase_difficulty: Нужно ли усложнить вопросы.
    :ivar correct_answer: Правильный ответ (если пользователь ошибся).
    :ivar extracted_info: Извлечённая информация о кандидате.
    :ivar demonstrated_level: Продемонстрированный уровень кандидата.
    """

    response_type: ResponseType
    quality: AnswerQuality
    is_factually_correct: bool
    detected_topics: list[str] = Field(default_factory=list)
    recommendation: str
    thoughts: list[InternalThought] = Field(default_factory=list)
    should_simplify: bool = False
    should_increase_difficulty: bool = False
    correct_answer: str | None = None
    extracted_info: ExtractedCandidateInfo | None = None
    demonstrated_level: str | None = None


class InterviewTurn(BaseModel):
    """
    Один ход интервью (формат по ТЗ).

    :ivar turn_id: Номер хода (начинается с 1).
    :ivar agent_visible_message: Сообщение агента пользователю.
    :ivar user_message: Сообщение пользователя.
    :ivar internal_thoughts: Внутренние мысли агентов (строка).
    :ivar timestamp: Время хода.
    """

    turn_id: int
    agent_visible_message: str
    user_message: str | None = None
    internal_thoughts: list[InternalThought] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_log_dict(self) -> dict[str, object]:
        """Преобразует в словарь для лога по формату ТЗ."""
        # Формат: [Observer]: ... [Interviewer]: ...
        thoughts_str = " ".join(
            f"[{t.from_agent}]: {t.content}" for t in self.internal_thoughts
        )
        return {
            "turn_id": self.turn_id,
            "agent_visible_message": self.agent_visible_message,
            "user_message": self.user_message or "",
            "internal_thoughts": thoughts_str,
        }


class DifficultyLevel(int, Enum):
    """Уровень сложности вопросов."""

    BASIC = 1
    INTERMEDIATE = 2
    ADVANCED = 3
    EXPERT = 4


class InterviewState(BaseModel):
    """
    Состояние интервью.

    :ivar participant_name: ФИО кандидата (для лога).
    :ivar candidate: Информация о кандидате (извлекается из диалога).
    :ivar turns: История ходов.
    :ivar current_turn: Текущий номер хода.
    :ivar current_difficulty: Текущий уровень сложности.
    :ivar covered_topics: Затронутые темы.
    :ivar confirmed_skills: Подтверждённые навыки.
    :ivar knowledge_gaps: Выявленные пробелы.
    :ivar is_active: Активно ли интервью.
    :ivar consecutive_good_answers: Подряд хороших ответов.
    :ivar consecutive_bad_answers: Подряд плохих ответов.
    """

    participant_name: str = "Неизвестный кандидат"
    candidate: CandidateInfo = Field(default_factory=CandidateInfo)
    turns: list[InterviewTurn] = Field(default_factory=list)
    current_turn: int = 0
    current_difficulty: DifficultyLevel = DifficultyLevel.BASIC
    covered_topics: list[str] = Field(default_factory=list)
    confirmed_skills: list[str] = Field(default_factory=list)
    knowledge_gaps: list[dict[str, str]] = Field(default_factory=list)
    is_active: bool = True
    consecutive_good_answers: int = 0
    consecutive_bad_answers: int = 0

    def add_turn(self, turn: InterviewTurn) -> None:
        """Добавляет ход в историю."""
        self.turns.append(turn)
        self.current_turn += 1

    def get_conversation_history(self) -> list[dict[str, str]]:
        """Возвращает историю разговора для LLM."""
        history: list[dict[str, str]] = []
        for turn in self.turns:
            history.append({"role": "assistant", "content": turn.agent_visible_message})
            if turn.user_message:
                history.append({"role": "user", "content": turn.user_message})
        return history

    def adjust_difficulty(self, analysis: ObserverAnalysis) -> None:
        """Корректирует сложность на основе анализа."""
        if analysis.should_increase_difficulty:
            self.consecutive_good_answers += 1
            self.consecutive_bad_answers = 0
            if self.consecutive_good_answers >= 2:
                if self.current_difficulty.value < DifficultyLevel.EXPERT.value:
                    self.current_difficulty = DifficultyLevel(
                        self.current_difficulty.value + 1
                    )
                self.consecutive_good_answers = 0
        elif analysis.should_simplify:
            self.consecutive_bad_answers += 1
            self.consecutive_good_answers = 0
            if self.consecutive_bad_answers >= 2:
                if self.current_difficulty.value > DifficultyLevel.BASIC.value:
                    self.current_difficulty = DifficultyLevel(
                        self.current_difficulty.value - 1
                    )
                self.consecutive_bad_answers = 0
        else:
            self.consecutive_good_answers = 0
            self.consecutive_bad_answers = 0


class LLMMessage(BaseModel):
    """
    Сообщение для LLM.

    :ivar role: Роль (system/user/assistant).
    :ivar content: Содержимое сообщения.
    """

    role: Literal["system", "user", "assistant"]
    content: str
