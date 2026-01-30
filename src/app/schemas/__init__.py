"""
Модуль схем данных.

Содержит Pydantic модели для интервью и фидбэка.
"""

from .EnvironmentOption import EnvironmentOption
from .feedback import (
    AssessedGrade,
    ClarityLevel,
    HiringRecommendation,
    InterviewFeedback,
    InterviewLog,
    PersonalRoadmap,
    RoadmapItem,
    SkillAssessment,
    SoftSkillsReview,
    TechnicalReview,
    Verdict,
)
from .interview import (
    AnswerQuality,
    CandidateInfo,
    DifficultyLevel,
    ExtractedCandidateInfo,
    GradeLevel,
    InternalThought,
    InterviewState,
    InterviewTurn,
    LLMMessage,
    ObserverAnalysis,
    ResponseType,
)

__all__ = [
    "EnvironmentOption",
    "AssessedGrade",
    "ClarityLevel",
    "HiringRecommendation",
    "InterviewFeedback",
    "InterviewLog",
    "PersonalRoadmap",
    "RoadmapItem",
    "SkillAssessment",
    "SoftSkillsReview",
    "TechnicalReview",
    "Verdict",
    "AnswerQuality",
    "CandidateInfo",
    "DifficultyLevel",
    "ExtractedCandidateInfo",
    "GradeLevel",
    "InternalThought",
    "InterviewState",
    "InterviewTurn",
    "LLMMessage",
    "ObserverAnalysis",
    "ResponseType",
]
