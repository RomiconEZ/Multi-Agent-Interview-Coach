"""
Схемы данных для финального фидбэка интервью.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class HiringRecommendation(str, Enum):
    """Рекомендация по найму."""

    STRONG_HIRE = "Strong Hire"
    HIRE = "Hire"
    NO_HIRE = "No Hire"


class AssessedGrade(str, Enum):
    """Оценённый грейд кандидата."""

    INTERN = "Intern"
    JUNIOR = "Junior"
    MIDDLE = "Middle"
    SENIOR = "Senior"
    LEAD = "Lead"


class Verdict(BaseModel):
    """
    Вердикт по кандидату.

    :ivar grade: Оценённый уровень.
    :ivar hiring_recommendation: Рекомендация по найму.
    :ivar confidence_score: Уверенность в оценке (0-100).
    """

    grade: AssessedGrade
    hiring_recommendation: HiringRecommendation
    confidence_score: int = Field(..., ge=0, le=100)

    @field_validator("confidence_score")
    @classmethod
    def validate_confidence(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("confidence_score must be between 0 and 100")
        return v


class SkillAssessment(BaseModel):
    """
    Оценка навыка.

    :ivar topic: Тема/навык.
    :ivar is_confirmed: Подтверждён ли навык.
    :ivar details: Детали оценки.
    :ivar correct_answer: Правильный ответ (для пробелов).
    """

    topic: str
    is_confirmed: bool
    details: str
    correct_answer: str | None = None


class TechnicalReview(BaseModel):
    """
    Анализ технических навыков.

    :ivar confirmed_skills: Подтверждённые навыки.
    :ivar knowledge_gaps: Выявленные пробелы.
    """

    confirmed_skills: list[SkillAssessment] = Field(default_factory=list)
    knowledge_gaps: list[SkillAssessment] = Field(default_factory=list)


class ClarityLevel(str, Enum):
    """Уровень ясности изложения."""

    EXCELLENT = "Excellent"
    GOOD = "Good"
    AVERAGE = "Average"
    POOR = "Poor"


class SoftSkillsReview(BaseModel):
    """
    Анализ софт-скиллов.

    :ivar clarity: Ясность изложения.
    :ivar clarity_details: Детали по ясности.
    :ivar honesty: Честность.
    :ivar honesty_details: Детали по честности.
    :ivar engagement: Вовлечённость.
    :ivar engagement_details: Детали по вовлечённости.
    """

    clarity: ClarityLevel
    clarity_details: str
    honesty: str
    honesty_details: str
    engagement: str
    engagement_details: str


class RoadmapItem(BaseModel):
    """
    Элемент роадмапа развития.

    :ivar topic: Тема для изучения.
    :ivar priority: Приоритет (1-5).
    :ivar reason: Причина включения.
    :ivar resources: Рекомендуемые ресурсы.
    """

    topic: str
    priority: int = Field(..., ge=1, le=5)
    reason: str
    resources: list[str] = Field(default_factory=list)


class PersonalRoadmap(BaseModel):
    """
    Персональный план развития.

    :ivar items: Элементы плана.
    :ivar summary: Краткое резюме.
    """

    items: list[RoadmapItem] = Field(default_factory=list)
    summary: str


class InterviewFeedback(BaseModel):
    """
    Полный финальный фидбэк по интервью.

    :ivar verdict: Вердикт.
    :ivar technical_review: Анализ технических навыков.
    :ivar soft_skills_review: Анализ софт-скиллов.
    :ivar roadmap: План развития.
    :ivar general_comments: Общие комментарии.
    """

    verdict: Verdict
    technical_review: TechnicalReview
    soft_skills_review: SoftSkillsReview
    roadmap: PersonalRoadmap
    general_comments: str

    def to_formatted_string(self) -> str:
        """Форматирует фидбэк в читаемую строку."""
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("ФИНАЛЬНЫЙ ФИДБЭК ПО ИНТЕРВЬЮ")
        lines.append("=" * 60)
        lines.append("")
        lines.append("📊 ВЕРДИКТ")
        lines.append("-" * 40)
        lines.append(f"Уровень: {self.verdict.grade.value}")
        lines.append(f"Рекомендация: {self.verdict.hiring_recommendation.value}")
        lines.append(f"Уверенность: {self.verdict.confidence_score}%")
        lines.append("")
        lines.append("💻 ТЕХНИЧЕСКИЕ НАВЫКИ")
        lines.append("-" * 40)
        if self.technical_review.confirmed_skills:
            lines.append("✅ Подтверждённые навыки:")
            for skill in self.technical_review.confirmed_skills:
                lines.append(f"  • {skill.topic}: {skill.details}")
        else:
            lines.append("✅ Подтверждённые навыки: нет данных")
        lines.append("")
        if self.technical_review.knowledge_gaps:
            lines.append("❌ Выявленные пробелы:")
            for gap in self.technical_review.knowledge_gaps:
                lines.append(f"  • {gap.topic}: {gap.details}")
                if gap.correct_answer:
                    lines.append(f"    Правильный ответ: {gap.correct_answer}")
        else:
            lines.append("❌ Выявленные пробелы: не обнаружено")
        lines.append("")
        lines.append("🤝 СОФТ-СКИЛЛЫ")
        lines.append("-" * 40)
        lines.append(f"Ясность изложения: {self.soft_skills_review.clarity.value}")
        lines.append(f"  {self.soft_skills_review.clarity_details}")
        lines.append(f"Честность: {self.soft_skills_review.honesty}")
        lines.append(f"  {self.soft_skills_review.honesty_details}")
        lines.append(f"Вовлечённость: {self.soft_skills_review.engagement}")
        lines.append(f"  {self.soft_skills_review.engagement_details}")
        lines.append("")
        lines.append("🗺️ ПЛАН РАЗВИТИЯ")
        lines.append("-" * 40)
        lines.append(self.roadmap.summary)
        lines.append("")
        if self.roadmap.items:
            for item in sorted(self.roadmap.items, key=lambda x: x.priority):
                lines.append(f"[Приоритет {item.priority}] {item.topic}")
                lines.append(f"  Причина: {item.reason}")
                if item.resources:
                    lines.append(f"  Ресурсы: {', '.join(item.resources)}")
        lines.append("")
        lines.append("📝 ОБЩИЕ КОММЕНТАРИИ")
        lines.append("-" * 40)
        lines.append(self.general_comments)
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)


class InterviewLog(BaseModel):
    """
    Лог интервью для сохранения в файл (формат по ТЗ).

    :ivar turns: История ходов.
    :ivar final_feedback: Финальный фидбэк.
    """

    turns: list[dict[str, object]]
    final_feedback: str | None = None
