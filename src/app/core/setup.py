from asyncio import Event
from collections.abc import AsyncGenerator, Callable
from contextlib import _AsyncGeneratorContextManager, asynccontextmanager
from typing import Any

import anyio
import fastapi
import redis.asyncio as redis
from fastapi import APIRouter, FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from .config import Settings
from .logger_setup import get_system_logger
from ..middleware.client_cache_middleware import ClientCacheMiddleware
from ..utils import cache

logger_system = get_system_logger(__name__)


async def set_threadpool_tokens(number_of_tokens: int) -> None:
    """
    Настраивает размер threadpool, чтобы ограничить параллелизм при использовании
    to_thread.* в anyio. По умолчанию 100 тредов для операций ввода-вывода.

    :param number_of_tokens: Количество токенов (потоков) для пула.
    """
    logger_system.info(f"Configuring threadpool with {number_of_tokens} tokens.")
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = number_of_tokens
    logger_system.debug("Threadpool configured.")


async def create_redis_cache_pool(redis_url: str) -> None:
    """
    Создаёт подключение к Redis, используемое для кэширования.

    :param redis_url: URL подключения к Redis.
    """
    logger_system.info(f"Creating Redis cache pool at {redis_url}.")
    pool = redis.ConnectionPool.from_url(redis_url)
    client = redis.Redis.from_pool(pool)
    cache.set_redis_connection(pool, client)
    logger_system.info("Redis cache pool created.")


async def close_redis_cache_pool() -> None:
    """
    Закрывает подключение к Redis, если оно инициализировано.
    """
    logger_system.info("Initiating Redis cache pool shutdown.")
    if cache.is_redis_connected():
        client = cache.get_redis_client()
        await client.aclose()  # type: ignore[attr-defined]
        logger_system.debug("Redis client closed.")
    cache.clear_redis_connection()
    logger_system.info("Redis cache pool shut down.")


def lifespan_factory(
        settings: Settings,
        threadpool_tokens: int,
) -> Callable[[FastAPI], _AsyncGeneratorContextManager[Any]]:
    """
    Фабрика, возвращающая функцию lifespan (контекст запуска и остановки приложения).

    :param settings: Объект настроек приложения.
    :param threadpool_tokens: Количество токенов для пула потоков.
    :return: Функция lifespan для FastAPI.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger_system.info("Starting application lifespan.")
        initialization_complete = Event()
        app.state.initialization_complete = initialization_complete

        redis_cache_created = False

        await set_threadpool_tokens(threadpool_tokens)

        try:
            await create_redis_cache_pool(settings.REDIS_CACHE_URL)
            redis_cache_created = True
            logger_system.info("Redis cache pool successfully created.")

            initialization_complete.set()
            logger_system.info("Initialization completed. Application is ready.")
            yield

        finally:
            if redis_cache_created:
                await close_redis_cache_pool()

            logger_system.info("Application lifespan finished.")

    return lifespan


def create_application(
        router: APIRouter,
        settings: Settings,
        threadpool_tokens: int = 100,
        **kwargs: Any,
) -> FastAPI:
    """
    Создаёт FastAPI-приложение с нужными роутерами, middleware и lifecycle-логикой.

    Документация (/docs, /redoc, /openapi.json) доступна всегда на уровне приложения.
    Ограничение доступа к документации осуществляется через nginx (блокировка извне).

    :param router: Основной роутер приложения.
    :param settings: Объект настроек приложения.
    :param threadpool_tokens: Количество токенов для пула потоков (по умолчанию 100).
    :param kwargs: Дополнительные параметры для FastAPI.
    :return: Настроенный экземпляр FastAPI.
    """
    logger_system.info("Creating FastAPI application.")

    # --- метаданные приложения ------------------------------------------------
    kwargs.update(
        {
            "title": settings.APP_NAME,
            "description": settings.APP_DESCRIPTION,
            "contact": {
                "name": settings.CONTACT_NAME,
                "email": settings.CONTACT_EMAIL,
            },
            "license_info": {"name": settings.LICENSE_NAME},
            "docs_url": None,
            "redoc_url": None,
            "openapi_url": None,
        }
    )
    logger_system.info("Applied application settings configuration.")

    # --- инициализация --------------------------------------------------------
    lifespan = lifespan_factory(settings, threadpool_tokens)
    application = FastAPI(lifespan=lifespan, **kwargs)
    application.include_router(router)
    logger_system.info("Main router included.")

    # --- middleware -----------------------------------------------------------

    application.add_middleware(
        ClientCacheMiddleware, max_age=settings.CLIENT_CACHE_MAX_AGE
    )
    logger_system.info("Added ClientCacheMiddleware.")

    # --- документация ---------------------------------------------------------
    # Документация всегда доступна на уровне приложения.
    # Ограничение доступа осуществляется через nginx (блокировка /docs, /redoc, /openapi.json извне).
    docs_router = APIRouter()

    @docs_router.get("/docs", include_in_schema=False)
    async def get_swagger_documentation() -> fastapi.responses.HTMLResponse:
        return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")

    @docs_router.get("/redoc", include_in_schema=False)
    async def get_redoc_documentation() -> fastapi.responses.HTMLResponse:
        return get_redoc_html(openapi_url="/openapi.json", title="docs")

    @docs_router.get("/openapi.json", include_in_schema=False)
    async def openapi() -> dict[str, Any]:
        return get_openapi(
            title=application.title,
            version=application.version,
            routes=application.routes,
        )

    application.include_router(docs_router)
    logger_system.info(
        "Documentation routes included. External access is restricted by nginx."
    )

    logger_system.info("FastAPI application created.")
    return application