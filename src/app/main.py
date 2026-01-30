"""
Точка входа FastAPI приложения.
"""

from .api import router
from .core.config import settings
from .core.logger_setup import setup_logging
from .core.setup import create_application

setup_logging()
app = create_application(router=router, settings=settings, threadpool_tokens=100)
