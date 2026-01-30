"""
Агент-наблюдатель (Observer).

Анализирует ответы кандидата, проверяет факты и даёт рекомендации интервьюеру.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..core.logger_setup import get_system_logger
from ..llm.client import LLMClient
from ..schemas.interview import (
    AnswerQuality,
    InternalThought,
    InterviewState,
    ObserverAnalysis,
    ResponseType,
)
from .base import BaseAgent

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


OBSERVER_SYSTEM_PROMPT = """Ты - Observer Agent (Агент-Наблюдатель) в системе технического интервью.

Твоя роль: анализировать ответы кандидата и давать рекомендации Interviewer Agent.

КРИТИЧЕСКИ ВАЖНО:
1. Ты ДОЛЖЕН выявлять галлюцинации и ложные утверждения кандидата
2. Ты ДОЛЖЕН распознавать попытки сменить тему (off-topic) и ЖЁСТКО возвращать к интервью
3. Ты ДОЛЖЕН оценивать качество технических ответов
4. Ты ДОЛЖЕН извлекать информацию о кандидате из ЛЮБОГО неструктурированного сообщения
5. Ты ДОЛЖЕН определять INTENT (намерение) пользователя, а не искать конкретные слова

ИЗВЛЕЧЕНИЕ ИНФОРМАЦИИ О КАНДИДАТЕ:
Из сообщения вроде "Я Александр, 5 лет работаю Python Backend-разработчиком, сейчас на Senior позиции" извлеки:
- name: "Александр"
- position: "Python Backend-разработчик" 
- grade: "Senior"
- experience: "5 лет опыта в Python Backend"
- technologies: ["Python", "Backend"]

ВАЖНО про технологии: Извлекай ВСЕ упомянутые технологии (Python, Django, SQL, Docker, etc.) - это критично для релевантных вопросов!

ОПРЕДЕЛЕНИЕ INTENT ЗАВЕРШЕНИЯ:
Распознавай НАМЕРЕНИЕ завершить, а не конкретные слова. Примеры intent завершения:
- "стоп", "хватит", "достаточно", "заканчиваем"
- "давай фидбэк", "покажи результаты", "как я справился?"
- "у меня всё", "больше вопросов нет", "на этом закончим"
- "спасибо, достаточно", "можно завершать"
- Любое сообщение с явным намерением прекратить интервью

ТИПЫ ОТВЕТОВ:
- "normal" - обычный технический ответ
- "hallucination" - кандидат уверенно говорит ЛОЖЬ (несуществующие версии, функции, концепции)
- "off_topic" - кандидат пытается сменить тему, уйти от вопроса, поговорить о другом
- "question" - кандидат задаёт встречный вопрос ПО ТЕМЕ интервью
- "stop_command" - INTENT завершения интервью (см. выше)
- "introduction" - кандидат представляется или дополняет информацию о себе
- "incomplete" - неполный, уклончивый ответ или "не знаю"
- "excellent" - отличный развёрнутый ответ с примерами

ОЦЕНКА УРОВНЯ КАНДИДАТА:
Если кандидат демонстрирует знания ВЫШЕ заявленного уровня:
- should_increase_difficulty = true
- В thoughts объясни почему ("Кандидат показывает глубокие знания, уровень выше Junior")

Если кандидат "плывёт" на текущем уровне:
- should_simplify = true  
- В thoughts объясни ("Кандидат затрудняется с базовыми вопросами")

КАЧЕСТВО ОТВЕТА:
- "excellent" - полный, точный, с примерами, глубокое понимание
- "good" - правильный, демонстрирует понимание
- "acceptable" - частично правильный, есть пробелы
- "poor" - слабый ответ, много ошибок
- "wrong" - фактически неверный ответ

OFF-TOPIC ДЕТЕКЦИЯ (КРИТИЧЕСКИ ВАЖНО):
Распознавай попытки:
- Сменить тему разговора
- Поговорить о погоде, личной жизни, не относящемся к интервью
- Уйти от технического вопроса
- Перевести разговор на другие технологии (не из опыта кандидата)
При off-topic: response_type = "off_topic", recommendation = "Вернуть к техническому вопросу"

Отвечай ТОЛЬКО в формате JSON:
{
  "response_type": "<тип ответа>",
  "quality": "<качество>",
  "is_factually_correct": true/false,
  "detected_topics": ["тема1", "тема2"],
  "recommendation": "конкретная рекомендация для интервьюера",
  "should_simplify": true/false,
  "should_increase_difficulty": true/false,
  "correct_answer": "правильный ответ если кандидат ошибся" или null,
  "extracted_info": {
    "name": "имя" или null,
    "position": "позиция" или null,
    "grade": "Intern/Junior/Middle/Senior/Lead" или null,
    "experience": "описание опыта" или null,
    "technologies": ["tech1", "tech2"] или []
  },
  "demonstrated_level": "Intern/Junior/Middle/Senior/Lead или null - реальный уровень по ответу",
  "thoughts": "подробный анализ ответа и рекомендации"
}"""


class ObserverAgent(BaseAgent):
    """
    Агент-наблюдатель.

    Анализирует ответы кандидата, выявляет галлюцинации, off-topic и даёт рекомендации.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        super().__init__("Observer_Agent", llm_client)

    @property
    def system_prompt(self) -> str:
        """Возвращает системный промпт."""
        return OBSERVER_SYSTEM_PROMPT

    async def process(
        self,
        state: InterviewState,
        user_message: str,
        last_question: str,
        **kwargs: Any,
    ) -> ObserverAnalysis:
        """
        Анализирует ответ кандидата.

        :param state: Состояние интервью.
        :param user_message: Ответ кандидата.
        :param last_question: Последний вопрос интервьюера.
        :return: Результат анализа.
        """
        context = self._build_analysis_context(state, user_message, last_question)
        messages = self._build_messages(context)

        try:
            response = await self._llm_client.complete_json(
                messages, temperature=0.3, max_tokens=1500
            )
            return self._parse_analysis(response, user_message)
        except Exception as e:
            logger.error(f"Observer analysis failed: {e}")
            return self._create_fallback_analysis(user_message)

    def _build_analysis_context(
        self,
        state: InterviewState,
        user_message: str,
        last_question: str,
    ) -> str:
        """Строит контекст для анализа."""
        history_summary = self._summarize_history(state)

        # Безопасное получение данных кандидата (могут быть None)
        candidate_name = state.candidate.name or "Неизвестно"
        candidate_position = state.candidate.position or "Не указана"
        candidate_grade = state.candidate.target_grade.value if state.candidate.target_grade else "Не указан"
        candidate_experience = state.candidate.experience or "Не указан"
        candidate_technologies = ", ".join(state.candidate.technologies) if state.candidate.technologies else "Не указаны"

        return f"""КОНТЕКСТ ИНТЕРВЬЮ:
Кандидат: {candidate_name}
Позиция: {candidate_position}
Целевой грейд: {candidate_grade}
Опыт: {candidate_experience}
Технологии: {candidate_technologies}
Текущая сложность: {state.current_difficulty.name}

ИСТОРИЯ ИНТЕРВЬЮ:
{history_summary}

ПОСЛЕДНИЙ ВОПРОС ИНТЕРВЬЮЕРА:
{last_question}

ОТВЕТ КАНДИДАТА:
{user_message}

Проанализируй ответ кандидата. Особое внимание:
1. Есть ли фактические ошибки или галлюцинации (например, ссылки на несуществующие версии Python, выдуманные функции)?
2. Пытается ли кандидат сменить тему или уйти от ответа?
3. Это команда завершить интервью (распознай INTENT: стоп, хватит, давай фидбэк, как я справился, достаточно)?
4. Задаёт ли кандидат встречный вопрос?
5. Насколько полный и качественный ответ?
6. Если кандидат представляется — извлеки ВСЕ данные: имя, позиция, грейд, опыт, технологии!"""

    def _summarize_history(self, state: InterviewState) -> str:
        """Создаёт краткое резюме истории."""
        if not state.turns:
            return "Интервью только началось."

        summary_parts: list[str] = []
        for turn in state.turns[-5:]:
            summary_parts.append(f"Агент: {turn.agent_visible_message[:100]}...")
            if turn.user_message:
                summary_parts.append(f"Кандидат: {turn.user_message[:100]}...")

        return "\n".join(summary_parts)

    def _parse_analysis(
        self,
        response: dict[str, Any],
        user_message: str,
    ) -> ObserverAnalysis:
        """Парсит ответ LLM в ObserverAnalysis."""
        from ..schemas.interview import ExtractedCandidateInfo

        try:
            response_type = ResponseType(response.get("response_type", "normal"))
        except ValueError:
            response_type = ResponseType.NORMAL

        try:
            quality = AnswerQuality(response.get("quality", "acceptable"))
        except ValueError:
            quality = AnswerQuality.ACCEPTABLE

        thoughts_content = response.get("thoughts", "Анализ выполнен.")
        thought = InternalThought(
            from_agent="Observer",
            to_agent="Interviewer",
            content=thoughts_content,
        )

        # Извлечение информации о кандидате
        extracted_data = response.get("extracted_info", {})
        extracted_info = None
        if extracted_data and any(v for k, v in extracted_data.items() if k != "technologies"):
            extracted_info = ExtractedCandidateInfo(
                name=extracted_data.get("name"),
                position=extracted_data.get("position"),
                grade=extracted_data.get("grade"),
                experience=extracted_data.get("experience"),
                technologies=extracted_data.get("technologies", []),
            )
        elif extracted_data.get("technologies"):
            # Только технологии
            extracted_info = ExtractedCandidateInfo(
                technologies=extracted_data.get("technologies", []),
            )

        return ObserverAnalysis(
            response_type=response_type,
            quality=quality,
            is_factually_correct=response.get("is_factually_correct", True),
            detected_topics=response.get("detected_topics", []),
            recommendation=response.get("recommendation", "Продолжай интервью"),
            thoughts=[thought],
            should_simplify=response.get("should_simplify", False),
            should_increase_difficulty=response.get("should_increase_difficulty", False),
            correct_answer=response.get("correct_answer"),
            extracted_info=extracted_info,
            demonstrated_level=response.get("demonstrated_level"),
        )

    def _create_fallback_analysis(self, user_message: str) -> ObserverAnalysis:
        """Создаёт резервный анализ при ошибке."""
        lower_msg = user_message.lower()

        if any(cmd in lower_msg for cmd in ["стоп", "stop", "хватит", "фидбэк", "завершить", "стоп игра"]):
            response_type = ResponseType.STOP_COMMAND
        elif "?" in user_message:
            response_type = ResponseType.QUESTION
        else:
            response_type = ResponseType.NORMAL

        thought = InternalThought(
            from_agent="Observer",
            to_agent="Interviewer",
            content="Fallback analysis used due to LLM error.",
        )

        return ObserverAnalysis(
            response_type=response_type,
            quality=AnswerQuality.ACCEPTABLE,
            is_factually_correct=True,
            detected_topics=[],
            recommendation="Продолжай интервью",
            thoughts=[thought],
        )
