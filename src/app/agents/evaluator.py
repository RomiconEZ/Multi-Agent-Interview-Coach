"""
Агент-оценщик (Evaluator).

Формирует финальный фидбэк по результатам интервью.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseAgent
from .prompts import EVALUATOR_SYSTEM_PROMPT
from ..core.logger_setup import get_system_logger
from ..llm.client import LLMClient, LLMClientError
from ..llm.response_parser import extract_json_from_llm_response
from ..schemas.agent_settings import SingleAgentConfig
from ..schemas.feedback import (
    AssessedGrade,
    ClarityLevel,
    HiringRecommendation,
    InterviewFeedback,
    PersonalRoadmap,
    RoadmapItem,
    SkillAssessment,
    SoftSkillsReview,
    TechnicalReview,
    Verdict,
)
from ..schemas.interview import InterviewState

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


class EvaluatorAgent(BaseAgent):
    """
    Агент-оценщик.

    Анализирует результаты интервью и формирует детальный фидбэк.
    """

    def __init__(self, llm_client: LLMClient, config: SingleAgentConfig) -> None:
        super().__init__("Evaluator_Agent", llm_client, config)

    @property
    def system_prompt(self) -> str:
        """Возвращает системный промпт."""
        return EVALUATOR_SYSTEM_PROMPT

    async def process(
            self,
            state: InterviewState,
            **kwargs: Any,
    ) -> InterviewFeedback:
        """
        Генерирует финальный фидбэк.

        При ошибке парсинга ответа LLM повторяет генерацию до
        ``generation_retries`` раз. Если все попытки исчерпаны —
        пробрасывает исключение.

        :param state: Состояние интервью.
        :return: Структурированный фидбэк.
        :raises LLMClientError: При ошибке сетевого взаимодействия с LLM.
        :raises ValueError: При невозможности распарсить ответ после всех попыток.
        """
        context: str = self._build_evaluation_context(state)
        messages: list[dict[str, str]] = self._build_messages(context)

        retries: int = self._config.generation_retries
        last_error: Exception | None = None

        for attempt in range(retries + 1):
            try:
                raw_response: str = await self._llm_client.complete(
                    messages,
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    generation_name="evaluator_feedback",
                )
                response: dict[str, Any] = extract_json_from_llm_response(raw_response)
                return self._parse_feedback(response, state)

            except LLMClientError:
                raise

            except Exception as e:
                last_error = e
                if attempt < retries:
                    logger.warning(
                        f"Evaluator generation parsing failed (attempt {attempt + 1}/{retries + 1}): "
                        f"{type(e).__name__}: {e}"
                    )
                    continue

        logger.error(
            f"Evaluator generation failed after {retries + 1} attempts: {last_error}"
        )
        raise last_error  # type: ignore[misc]

    def _build_evaluation_context(self, state: InterviewState) -> str:
        """
        Строит контекст для оценки.

        :param state: Состояние интервью.
        :return: Контекстная строка для LLM.
        """
        conversation: str = self._format_conversation(state)
        skills_summary: str = self._format_skills_summary(state)

        candidate_info_parts: list[str] = [
            f"Имя: {state.participant_name}",
        ]
        if state.candidate.position:
            candidate_info_parts.append(f"Позиция: {state.candidate.position}")
        if state.candidate.target_grade:
            candidate_info_parts.append(
                f"Целевой грейд: {state.candidate.target_grade.value}"
            )
        if state.candidate.experience:
            candidate_info_parts.append(
                f"Заявленный опыт: {state.candidate.experience}"
            )

        job_block: str = self._build_job_description_block(state.job_description)

        return f"""ИНФОРМАЦИЯ О КАНДИДАТЕ:
{chr(10).join(candidate_info_parts)}

СТАТИСТИКА ИНТЕРВЬЮ:
Всего ходов: {len(state.turns)}
Финальный уровень сложности: {state.current_difficulty.name}
{job_block}
ИСТОРИЯ ДИАЛОГА:
{conversation}

ПРЕДВАРИТЕЛЬНАЯ ОЦЕНКА НАВЫКОВ:
{skills_summary}

Сформируй детальный фидбэк по интервью. Следуй инструкциям из output_format:
1. Напиши рассуждения в <reasoning>...</reasoning>.
2. Выведи JSON в <r>...</r>.

Учти:
1. Соответствие заявленного грейда реальному уровню
2. Были ли галлюцинации или фактические ошибки
3. Как кандидат реагировал на сложные вопросы
4. Были ли бессмысленные сообщения (мусор, тест клавиатуры)
5. Soft skills: честность, ясность изложения, вовлечённость
6. Конкретные рекомендации по развитию
7. Если есть описание вакансии — оцени соответствие кандидата"""

    def _format_conversation(self, state: InterviewState) -> str:
        """
        Форматирует историю диалога.

        :param state: Состояние интервью.
        :return: Форматированная строка диалога.
        """
        lines: list[str] = []
        for turn in state.turns:
            lines.append(f"[Интервьюер]: {turn.agent_visible_message}")
            if turn.user_message:
                lines.append(f"[Кандидат]: {turn.user_message}")
            if turn.internal_thoughts:
                thoughts = "; ".join(t.content for t in turn.internal_thoughts)
                lines.append(f"[Внутренние мысли]: {thoughts}")
            lines.append("")
        return "\n".join(lines)

    def _format_skills_summary(self, state: InterviewState) -> str:
        """
        Форматирует сводку по навыкам.

        :param state: Состояние интервью.
        :return: Форматированная сводка.
        """
        lines: list[str] = []

        if state.confirmed_skills:
            lines.append("Подтверждённые навыки:")
            for skill in state.confirmed_skills:
                lines.append(f"  ✅ {skill}")

        if state.knowledge_gaps:
            lines.append("Выявленные пробелы:")
            for gap in state.knowledge_gaps:
                topic: str = gap.get("topic", "неизвестно")
                answer: str = gap.get("correct_answer", "")
                lines.append(f"  ❌ {topic}")
                if answer:
                    lines.append(f"     Правильный ответ: {answer}")

        if state.covered_topics:
            lines.append(f"Затронутые темы: {', '.join(state.covered_topics)}")

        return "\n".join(lines) if lines else "Данные отсутствуют"

    def _parse_feedback(
            self,
            response: dict[str, Any],
            state: InterviewState,
    ) -> InterviewFeedback:
        """
        Парсит ответ LLM в InterviewFeedback.

        Использует паттерн ``response.get(key) or {}`` вместо
        ``response.get(key, {})`` для защиты от случая, когда LLM
        возвращает явный ``null`` в качестве значения вложенного объекта.
        ``dict.get(key, default)`` возвращает ``default`` только если ключ
        отсутствует, но НЕ если значение равно ``None``.

        :param response: Распарсенный JSON-ответ LLM.
        :param state: Состояние интервью.
        :return: Структурированный фидбэк.
        """
        verdict_data: dict[str, Any] = response.get("verdict") or {}
        verdict = Verdict(
            grade=_parse_grade(verdict_data.get("grade", "Junior")),
            hiring_recommendation=_parse_hiring_rec(
                verdict_data.get("hiring_recommendation", "No Hire")
            ),
            confidence_score=min(100, max(0, verdict_data.get("confidence_score", 50))),
        )

        tech_data: dict[str, Any] = response.get("technical_review") or {}
        technical_review = TechnicalReview(
            confirmed_skills=[
                SkillAssessment(**s)
                for s in (tech_data.get("confirmed_skills") or [])
                if isinstance(s, dict)
            ],
            knowledge_gaps=[
                SkillAssessment(**s)
                for s in (tech_data.get("knowledge_gaps") or [])
                if isinstance(s, dict)
            ],
        )

        soft_data: dict[str, Any] = response.get("soft_skills_review") or {}
        soft_skills_review = SoftSkillsReview(
            clarity=_parse_clarity(soft_data.get("clarity", "Average")),
            clarity_details=soft_data.get("clarity_details", ""),
            honesty=soft_data.get("honesty", "Не определено"),
            honesty_details=soft_data.get("honesty_details", ""),
            engagement=soft_data.get("engagement", "Не определено"),
            engagement_details=soft_data.get("engagement_details", ""),
        )

        roadmap_data: dict[str, Any] = response.get("roadmap") or {}
        roadmap = PersonalRoadmap(
            items=[
                RoadmapItem(**item)
                for item in (roadmap_data.get("items") or [])
                if isinstance(item, dict)
            ],
            summary=roadmap_data.get("summary", "План развития не сформирован"),
        )

        return InterviewFeedback(
            verdict=verdict,
            technical_review=technical_review,
            soft_skills_review=soft_skills_review,
            roadmap=roadmap,
            general_comments=response.get("general_comments", ""),
        )


def _parse_grade(grade_str: str) -> AssessedGrade:
    """
    Парсит строку грейда.

    :param grade_str: Строковое представление грейда.
    :return: Значение перечисления AssessedGrade.
    """
    mapping: dict[str, AssessedGrade] = {
        "intern": AssessedGrade.INTERN,
        "junior": AssessedGrade.JUNIOR,
        "middle": AssessedGrade.MIDDLE,
        "senior": AssessedGrade.SENIOR,
        "lead": AssessedGrade.LEAD,
    }
    return mapping.get(grade_str.lower(), AssessedGrade.JUNIOR)


def _parse_hiring_rec(rec_str: str) -> HiringRecommendation:
    """
    Парсит рекомендацию по найму.

    :param rec_str: Строковое представление рекомендации.
    :return: Значение перечисления HiringRecommendation.
    """
    lower: str = rec_str.lower()
    if "strong" in lower:
        return HiringRecommendation.STRONG_HIRE
    if "no" in lower:
        return HiringRecommendation.NO_HIRE
    return HiringRecommendation.HIRE


def _parse_clarity(clarity_str: str) -> ClarityLevel:
    """
    Парсит уровень ясности.

    :param clarity_str: Строковое представление уровня ясности.
    :return: Значение перечисления ClarityLevel.
    """
    mapping: dict[str, ClarityLevel] = {
        "excellent": ClarityLevel.EXCELLENT,
        "good": ClarityLevel.GOOD,
        "average": ClarityLevel.AVERAGE,
        "poor": ClarityLevel.POOR,
    }
    return mapping.get(clarity_str.lower(), ClarityLevel.AVERAGE)