# exceptions/base_exceptions.py

from fastapi import HTTPException


def _validate_status_code(status_code: int) -> None:
    """Проверяет, что status_code является целым числом в диапазоне 100–599."""
    if not isinstance(status_code, int):
        raise ValueError("status_code должен быть целым числом")
    if status_code < 100 or status_code > 599:
        raise ValueError("status_code должен быть в диапазоне от 100 до 599")


def _validate_detail(detail: str) -> None:
    """Проверяет, что detail является непустой строкой."""
    if not isinstance(detail, str):
        raise ValueError("detail должен быть строкой")
    if not detail.strip():
        raise ValueError("detail не может быть пустым")


class CustomException(HTTPException):
    """Базовый класс для пользовательских HTTP-исключений с обязательным полем status_code."""

    def __init__(self, status_code: int, detail: str):
        _validate_status_code(status_code)
        _validate_detail(detail)
        super().__init__(status_code=status_code, detail=detail)
