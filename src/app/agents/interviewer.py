"""
Агент-интервьюер (Interviewer).

Ведёт диалог с кандидатом, задаёт вопросы, учитывает рекомендации Observer.
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.logger_setup import get_system_logger
from ..llm.client import LLMClient
from ..schemas.interview import (
    DifficultyLevel,
    InternalThought,
    InterviewState,
    ObserverAnalysis,
    ResponseType,
)
from .base import BaseAgent

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)


INTERVIEWER_SYSTEM_PROMPT = """Ты - Interviewer Agent (Агент-Интервьюер) в системе технического интервью.

Твоя роль: вести технический диалог с кандидатом, задавать вопросы, оценивать ответы.

КРИТИЧЕСКИЕ ПРАВИЛА:

1. РЕЛЕВАНТНОСТЬ ВОПРОСОВ:
   - Задавай вопросы ТОЛЬКО по технологиям из опыта кандидата
   - Если кандидат указал Python, Django, SQL — спрашивай про Python, Django, SQL
   - НИКОГДА не спрашивай про технологии, которые кандидат не упоминал
   - Если технологии неизвестны — спроси про них в первую очередь

2. АДАПТИВНОСТЬ СЛОЖНОСТИ:
   - Начинай с уровня, соответствующего заявленному грейду
   - Если кандидат отвечает отлично — УСЛОЖНЯЙ вопросы
   - Если кандидат "плывёт" — УПРОЩАЙ или давай подсказки
   - Логируй изменения сложности в своих мыслях

3. ОБРАБОТКА ГАЛЛЮЦИНАЦИЙ:
   - Если Observer обнаружил галлюцинацию — ВЕЖЛИВО поправь
   - Объясни как на самом деле работает технология
   - Не унижай кандидата, но и не соглашайся с неверной информацией

4. ОБРАБОТКА OFF-TOPIC:
   - ЖЁСТКО возвращай к техническому интервью
   - Не поддерживай разговоры не по теме
   - Пример: "Давайте вернёмся к техническим вопросам. Итак, ..."

5. ВСТРЕЧНЫЕ ВОПРОСЫ КАНДИДАТА:
   - Если вопрос ПО ТЕМЕ интервью — ответь кратко и продолжай
   - Если вопрос off-topic — вежливо отклони и продолжай интервью

6. ОДИН ВОПРОС ЗА РАЗ:
   - Задавай только ОДИН технический вопрос
   - Дожидайся ответа перед следующим вопросом

УРОВНИ СЛОЖНОСТИ:
- BASIC: базовые понятия, синтаксис, простые примеры
- INTERMEDIATE: паттерны, best practices, типичные задачи
- ADVANCED: архитектура, оптимизация, edge cases
- EXPERT: системный дизайн, масштабирование, сложные кейсы

ФОРМАТ ОТВЕТА:
Отвечай естественно, как профессиональный интервьюер. Без JSON, без markdown."""


class InterviewerAgent(BaseAgent):
    """
    Агент-интервьюер.

    Ведёт диалог, задаёт вопросы, учитывает рекомендации наблюдателя.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        super().__init__("Interviewer_Agent", llm_client)

    @property
    def system_prompt(self) -> str:
        """Возвращает системный промпт."""
        return INTERVIEWER_SYSTEM_PROMPT

    async def generate_greeting(self, state: InterviewState) -> str:
        """
        Генерирует приветствие для начала интервью.

        :param state: Состояние интервью.
        :return: Приветственное сообщение.
        """
        context = """Начни техническое интервью.

Ты ещё не знаешь имени кандидата. Поприветствуй его и попроси представиться и рассказать о своём опыте.

Пример: "Привет! Расскажи про свой опыт в программировании." или "Здравствуйте! Расскажите немного о себе и своём опыте."

НЕ спрашивай про конкретную технологию пока не знаешь, на какую позицию претендует кандидат."""

        messages = self._build_messages(context)

        try:
            response = await self._llm_client.complete(
                messages, temperature=0.7, max_tokens=300
            )
            return response.strip()
        except Exception as e:
            logger.error(f"Failed to generate greeting: {e}")
            return "Привет! Расскажи про свой опыт в программировании."

    async def process(
        self,
        state: InterviewState,
        analysis: ObserverAnalysis,
        user_message: str,
        **kwargs: Any,
    ) -> tuple[str, list[InternalThought]]:
        """
        Генерирует следующую реплику на основе анализа.

        :param state: Состояние интервью.
        :param analysis: Анализ от Observer.
        :param user_message: Сообщение кандидата.
        :return: Tuple (ответ интервьюера, внутренние мысли).
        """
        thoughts: list[InternalThought] = list(analysis.thoughts)

        context = self._build_response_context(state, analysis, user_message)
        messages = self._build_messages(context, state.get_conversation_history())

        interviewer_thought = InternalThought(
            from_agent="Interviewer",
            to_agent="User",
            content=self._generate_thought(analysis),
        )
        thoughts.append(interviewer_thought)

        try:
            response = await self._llm_client.complete(
                messages, temperature=0.7, max_tokens=800
            )
            return response.strip(), thoughts
        except Exception as e:
            logger.error(f"Failed to generate response: {e}")
            return self._generate_fallback_response(analysis), thoughts

    def _build_response_context(
        self,
        state: InterviewState,
        analysis: ObserverAnalysis,
        user_message: str,
    ) -> str:
        """Строит контекст для генерации ответа."""
        context_parts: list[str] = [
            f"ИНФОРМАЦИЯ О КАНДИДАТЕ:",
        ]
        
        if state.candidate.name:
            context_parts.append(f"Имя: {state.candidate.name}")
        if state.candidate.position:
            context_parts.append(f"Позиция: {state.candidate.position}")
        if state.candidate.target_grade:
            context_parts.append(f"Заявленный грейд: {state.candidate.target_grade.value}")
        if state.candidate.experience:
            context_parts.append(f"Опыт: {state.candidate.experience}")
        if state.candidate.technologies:
            context_parts.append(f"Технологии: {', '.join(state.candidate.technologies)}")
            context_parts.append(f"ВАЖНО: Задавай вопросы ТОЛЬКО по этим технологиям!")
        
        if not any([state.candidate.name, state.candidate.position]):
            context_parts.append("(Данные ещё не известны - кандидат представляется)")
            
        context_parts.extend([
            f"",
            f"ТЕКУЩЕЕ СОСТОЯНИЕ:",
            f"Уровень сложности: {state.current_difficulty.name}",
            f"Подтверждённые навыки: {', '.join(state.confirmed_skills) or 'нет'}",
            f"Выявленные пробелы: {len(state.knowledge_gaps)}",
            f"",
            f"ПОСЛЕДНИЙ ОТВЕТ КАНДИДАТА:",
            f"{user_message}",
            f"",
            f"АНАЛИЗ ОТ OBSERVER:",
            f"Тип ответа: {analysis.response_type.value}",
            f"Качество: {analysis.quality.value}",
            f"Фактически верно: {analysis.is_factually_correct}",
            f"Рекомендация: {analysis.recommendation}",
        ])

        if analysis.demonstrated_level:
            context_parts.append(f"Продемонстрированный уровень: {analysis.demonstrated_level}")

        if analysis.correct_answer:
            context_parts.append(f"Правильный ответ: {analysis.correct_answer}")

        context_parts.append("")
        context_parts.append(self._get_response_instruction(analysis, state))

        return "\n".join(context_parts)

    def _get_response_instruction(
        self,
        analysis: ObserverAnalysis,
        state: InterviewState,
    ) -> str:
        """Возвращает инструкцию в зависимости от типа ответа."""
        response_type = analysis.response_type

        if response_type == ResponseType.INTRODUCTION:
            techs = state.candidate.technologies
            if techs:
                tech_list = ", ".join(techs[:3])  # Первые 3 технологии
                return (
                    f"Кандидат представился. Поблагодари за представление. "
                    f"Задай первый технический вопрос по одной из технологий: {tech_list}. "
                    f"Начни с уровня {state.current_difficulty.name}."
                )
            return (
                "Кандидат представился. Поблагодари за представление, "
                "и задай первый технический вопрос, подходящий под его позицию и опыт."
            )

        if response_type == ResponseType.HALLUCINATION:
            correct = analysis.correct_answer or "информацию можно найти в официальной документации"
            return (
                "ВАЖНО: Кандидат сказал фактически неверную информацию (галлюцинация). "
                f"Вежливо укажи на ошибку. Скажи что-то вроде: "
                f"'Хм, это довольно необычное утверждение. На самом деле {correct}. "
                f"Давайте вернёмся к текущей версии Python...' и задай уточняющий вопрос."
            )

        if response_type == ResponseType.OFF_TOPIC:
            return (
                "КРИТИЧНО: Кандидат пытается сменить тему или уйти от вопроса. "
                "НЕ поддерживай этот разговор. Скажи что-то вроде: "
                "'Давайте вернёмся к техническим вопросам.' и СРАЗУ задай технический вопрос "
                "по одной из технологий кандидата. НЕ отвечай на off-topic."
            )

        if response_type == ResponseType.QUESTION:
            return (
                "Кандидат задал встречный вопрос. Это хороший знак вовлечённости! "
                "Ответь на его вопрос развёрнуто и информативно (это важно для оценки!), "
                "затем плавно продолжи интервью с новым техническим вопросом."
            )

        if response_type == ResponseType.INCOMPLETE:
            return (
                "Ответ неполный. Попроси уточнить или раскрыть тему глубже, "
                "или помоги кандидату наводящим вопросом."
            )

        if response_type == ResponseType.EXCELLENT:
            techs = state.candidate.technologies
            if techs:
                tech_list = ", ".join(techs[:3])
                return (
                    f"Отличный ответ! Похвали кратко. Кандидат показывает хороший уровень. "
                    f"Задай более сложный вопрос уровня {state.current_difficulty.name} "
                    f"по одной из технологий: {tech_list}."
                )
            return (
                f"Отличный ответ! Похвали кратко и задай более сложный вопрос "
                f"уровня {state.current_difficulty.name}."
            )

        difficulty_hint = self._get_difficulty_hint(state.current_difficulty)
        techs = state.candidate.technologies
        if techs:
            tech_list = ", ".join(techs[:3])
            return (
                f"Продолжай интервью. Задай следующий технический вопрос "
                f"уровня {state.current_difficulty.name} по одной из технологий: {tech_list}. "
                f"{difficulty_hint}"
            )
        return (
            f"Продолжай интервью. Задай следующий технический вопрос "
            f"уровня {state.current_difficulty.name}. {difficulty_hint}"
        )

    def _get_difficulty_hint(self, difficulty: DifficultyLevel) -> str:
        """Возвращает подсказку по сложности."""
        hints = {
            DifficultyLevel.BASIC: "Фокус на определениях и базовых концепциях.",
            DifficultyLevel.INTERMEDIATE: "Фокус на практическом применении.",
            DifficultyLevel.ADVANCED: "Фокус на edge cases и оптимизации.",
            DifficultyLevel.EXPERT: "Фокус на архитектуре и сложных сценариях.",
        }
        return hints.get(difficulty, "")

    def _generate_thought(self, analysis: ObserverAnalysis) -> str:
        """Генерирует внутреннюю мысль интервьюера."""
        base_thoughts = {
            ResponseType.INTRODUCTION: "Кандидат представился. Анализирую опыт и технологии для релевантных вопросов.",
            ResponseType.HALLUCINATION: f"ALERT: Кандидат галлюцинирует! Нужно вежливо указать на ошибку и объяснить как на самом деле. Рекомендация: {analysis.recommendation}",
            ResponseType.OFF_TOPIC: "Кандидат пытается сменить тему. Возвращаю к техническому интервью.",
            ResponseType.QUESTION: "Кандидат задал встречный вопрос - хороший знак вовлечённости. Отвечу развёрнуто и продолжу.",
            ResponseType.EXCELLENT: f"Отличный ответ! Уровень {analysis.quality.value}. Можно усложнить вопросы.",
            ResponseType.INCOMPLETE: "Неполный или уклончивый ответ. Попрошу раскрыть тему или дам подсказку.",
        }
        return base_thoughts.get(
            analysis.response_type,
            f"Анализ: качество={analysis.quality.value}, корректность={analysis.is_factually_correct}. Рекомендация: {analysis.recommendation}",
        )

    def _generate_fallback_response(self, analysis: ObserverAnalysis) -> str:
        """Генерирует резервный ответ."""
        if analysis.response_type == ResponseType.HALLUCINATION:
            return (
                "Интересная мысль, но позвольте уточнить - я не встречал такой информации "
                "в официальной документации. Давайте вернёмся к основам - "
                "расскажите, как вы обычно работаете с этой технологией?"
            )

        if analysis.response_type == ResponseType.QUESTION:
            return (
                "Хороший вопрос! Давайте я отвечу кратко, а затем продолжим интервью. "
                "Что касается вашего вопроса - это зависит от конкретного проекта. "
                "А теперь следующий вопрос..."
            )

        return "Хорошо, давайте продолжим. Расскажите подробнее о вашем опыте в этой области."
