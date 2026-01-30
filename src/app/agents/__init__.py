"""
Модуль AI-агентов для системы интервью.

Содержит агентов: Observer, Interviewer, Evaluator.
"""

from .base import BaseAgent
from .evaluator import EvaluatorAgent
from .interviewer import InterviewerAgent
from .observer import ObserverAgent

__all__ = [
    "BaseAgent",
    "ObserverAgent",
    "InterviewerAgent",
    "EvaluatorAgent",
]
