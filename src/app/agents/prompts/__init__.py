"""
Модуль промптов для AI-агентов.

Содержит системные промпты для Observer, Interviewer и Evaluator.
"""

from .evaluator_prompt import EVALUATOR_SYSTEM_PROMPT
from .interviewer_prompt import INTERVIEWER_SYSTEM_PROMPT
from .observer_prompt import OBSERVER_SYSTEM_PROMPT

__all__ = [
    "OBSERVER_SYSTEM_PROMPT",
    "INTERVIEWER_SYSTEM_PROMPT",
    "EVALUATOR_SYSTEM_PROMPT",
]