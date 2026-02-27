"""
Гибкий парсер ответов LLM.

Извлекает структурированный JSON из ответов моделей, которые могут содержать
рассуждения (reasoning) перед структурированным выводом. Поддерживает
множественные форматы обёрток: XML-теги, markdown code blocks, сырой JSON.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..core.logger_setup import get_system_logger

logger: logging.LoggerAdapter[logging.Logger] = get_system_logger(__name__)

_R_TAG_PATTERN: re.Pattern[str] = re.compile(
    r"<r\s*>(.*?)</r\s*>",
    re.DOTALL | re.IGNORECASE,
)

_RESULT_TAG_PATTERN: re.Pattern[str] = re.compile(
    r"<result\s*>(.*?)</result\s*>",
    re.DOTALL | re.IGNORECASE,
)

_JSON_CODE_BLOCK_PATTERN: re.Pattern[str] = re.compile(
    r"```(?:json)?\s*\n?(.*?)```",
    re.DOTALL,
)


def extract_json_from_llm_response(text: str) -> dict[str, Any]:
    """
    Извлекает JSON-объект из текстового ответа LLM.

    Стратегия извлечения (по приоритету):

    1. Ищет содержимое внутри ``<r>...</r>`` тегов.
    2. Ищет содержимое внутри ``<result>...</result>`` тегов.
    3. Ищет содержимое внутри markdown code block (````json ... ``` ``).
    4. Ищет первый валидный JSON-объект ``{...}`` в тексте.

    На каждом шаге пытается распарсить найденный фрагмент как JSON.

    :param text: Текстовый ответ LLM (может содержать рассуждения + JSON).
    :return: Распарсенный JSON-объект.
    :raises ValueError: Если валидный JSON не найден ни одним способом.
    """
    if not text or not text.strip():
        raise ValueError("Empty LLM response")

    # Стратегия 1: <r>...</r>
    r_match: re.Match[str] | None = _R_TAG_PATTERN.search(text)
    if r_match:
        inner: str = r_match.group(1).strip()
        parsed: dict[str, Any] | None = _try_parse_json(inner)
        if parsed is not None:
            logger.debug("JSON extracted from <r> tags")
            return parsed

    # Стратегия 2: <result>...</result>
    result_match: re.Match[str] | None = _RESULT_TAG_PATTERN.search(text)
    if result_match:
        inner = result_match.group(1).strip()
        parsed = _try_parse_json(inner)
        if parsed is not None:
            logger.debug("JSON extracted from <result> tags")
            return parsed

    # Стратегия 3: ```json ... ```
    code_match: re.Match[str] | None = _JSON_CODE_BLOCK_PATTERN.search(text)
    if code_match:
        inner = code_match.group(1).strip()
        parsed = _try_parse_json(inner)
        if parsed is not None:
            logger.debug("JSON extracted from markdown code block")
            return parsed

    # Стратегия 4: Сырой JSON-объект в тексте
    parsed = _extract_raw_json_object(text)
    if parsed is not None:
        logger.debug("JSON extracted as raw object from text")
        return parsed

    raise ValueError(
        f"No valid JSON found in LLM response (length={len(text)}): "
        f"{text[:300]}"
    )


def extract_reasoning_from_llm_response(text: str) -> str | None:
    """
    Извлекает блок рассуждений из ответа LLM.

    Ищет содержимое внутри ``<reasoning>...</reasoning>`` тегов.

    :param text: Текстовый ответ LLM.
    :return: Текст рассуждений или None, если блок не найден.
    """
    pattern: re.Pattern[str] = re.compile(
        r"<reasoning\s*>(.*?)</reasoning\s*>",
        re.DOTALL | re.IGNORECASE,
    )
    match: re.Match[str] | None = pattern.search(text)
    if match:
        return match.group(1).strip()
    return None


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """
    Пытается распарсить строку как JSON-объект.

    :param text: Строка для парсинга.
    :return: Словарь или None при неудаче.
    """
    cleaned: str = text.strip()
    if not cleaned:
        return None

    try:
        result: Any = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    return None


def _extract_raw_json_object(text: str) -> dict[str, Any] | None:
    """
    Находит и извлекает первый валидный JSON-объект из произвольного текста.

    Использует поиск сбалансированных фигурных скобок, начиная
    с первого символа ``{``.

    :param text: Произвольный текст, содержащий JSON.
    :return: Распарсенный словарь или None.
    """
    start: int = text.find("{")
    if start == -1:
        return None

    # Пробуем от первого '{' до последнего '}'
    end: int = text.rfind("}")
    if end <= start:
        return None

    candidate: str = text[start: end + 1]
    parsed: dict[str, Any] | None = _try_parse_json(candidate)
    if parsed is not None:
        return parsed

    # Fallback: ищем минимальный сбалансированный JSON с первого '{'
    depth: int = 0
    in_string: bool = False
    escape_next: bool = False

    for i in range(start, len(text)):
        ch: str = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            if in_string:
                escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start: i + 1]
                parsed = _try_parse_json(candidate)
                if parsed is not None:
                    return parsed
                break

    return None