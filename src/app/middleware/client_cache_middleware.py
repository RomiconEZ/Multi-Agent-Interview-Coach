"""
Middleware для кэширования на стороне клиента.
"""

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class ClientCacheMiddleware(BaseHTTPMiddleware):
    """
    Middleware для установки заголовка Cache-Control.

    :ivar max_age: Время кэширования в секундах.
    """

    def __init__(self, app: FastAPI, max_age: int = 60) -> None:
        super().__init__(app)
        self.max_age = max_age

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Обрабатывает запрос и устанавливает Cache-Control.

        :param request: Входящий запрос.
        :param call_next: Следующий обработчик.
        :return: Ответ с заголовком Cache-Control.
        """
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = f"public, max-age={self.max_age}"
        return response
