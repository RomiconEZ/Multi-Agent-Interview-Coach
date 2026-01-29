from __future__ import annotations

import os
from urllib.parse import unquote


def sanitize_filename(raw_filename: str) -> str:
    """
    Нормализует имя файла, полученное от клиента.

    • Декодирует percent-encoded символы (в т. ч. русские буквы).
    • Удаляет путь, оставляя только basename.
    • Убирает управляющие символы и null-байты.

    Args:
        raw_filename: Имя файла из UploadFile.filename.

    Returns:
        str: Безопасное и человекочитаемое имя файла.
    """
    # 1) Декодирование RFC 5987 / percent-encoding
    decoded = unquote(raw_filename, encoding="utf-8", errors="replace")

    # 2) Отсекаем путь на случай, если клиент прислал «C:\\tmp\\file.txt»
    decoded = os.path.basename(decoded)

    # 3) Удаляем нулевые байты и прочие управляющие символы
    cleaned = "".join(ch for ch in decoded if ch.isprintable() and ch != "\x00")

    if not cleaned:
        raise ValueError("Имя файла не может быть пустым после очистки.")

    return cleaned
