# Spec: Serving / Config — Multi-Agent Interview Coach

Техническая спецификация модулей запуска, конфигурации, секретов и версий моделей.

---

## 1. Обзор

Система запускается в двух режимах:

| Режим | Точка входа | Контейнер | Сервер |
|---|---|---|---|
| **Gradio UI** | `src/app/gradio_main.py` | `interview-coach` (`Dockerfile.gradio`) | Gradio built-in (uvicorn) |
| **FastAPI Backend** | `src/app/main.py` | `backend` (`Dockerfile`) | Gunicorn + Uvicorn workers |

Оба режима загружают конфигурацию из `.env` файла через `pydantic-settings`.

---

## 2. Конфигурация (Settings)

### 2.1 Файл: `src/app/core/config.py`

Единая точка конфигурации. Все настройки объединены в класс `Settings`, наследующий от 10 групп:

| Группа | Класс | Ключевые параметры |
|---|---|---|
| Приложение | `AppSettings` | `APP_NAME`, `APP_DESCRIPTION`, `APP_VERSION`, `LICENSE_NAME`, `CONTACT_NAME`, `CONTACT_EMAIL` |
| Окружение | `EnvironmentSettings` | `ENVIRONMENT` (enum: `LOCAL`, `STAGING`, `PRODUCTION`) |
| Redis | `RedisCacheSettings` | `REDIS_CACHE_HOST`, `REDIS_CACHE_PORT` → computed `REDIS_CACHE_URL` |
| Client Cache | `ClientSideCacheSettings` | `CLIENT_CACHE_MAX_AGE` (default: 60s) |
| Логирование | `LogSettings` | `APP_TZ_OFFSET`, `APP_LOG_DIR`, `LOG_MAX_BYTES` (10 MB), `LOG_BACKUP_COUNT` (2) → computed `SYSTEM_LOG_PATH`, `PERSONAL_LOG_PATH` |
| LiteLLM | `LiteLLMSettings` | `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `LITELLM_MODEL`, `LITELLM_TIMEOUT` (120s), `LITELLM_MAX_RETRIES` (3), `LITELLM_RETRY_BACKOFF_BASE` (0.5), `LITELLM_RETRY_BACKOFF_MAX` (30.0), `LITELLM_MODELS_FETCH_TIMEOUT` (10.0), `LITELLM_HEALTH_CHECK_TIMEOUT` (5.0), `LITELLM_CIRCUIT_BREAKER_THRESHOLD` (5), `LITELLM_CIRCUIT_BREAKER_RECOVERY` (60.0) |
| Интервью | `InterviewSettings` | `INTERVIEW_LOG_DIR`, `TEAM_NAME`, `MAX_TURNS` (20), `HISTORY_WINDOW_TURNS` (10), `GREETING_MAX_TOKENS` (300) |
| Langfuse | `LangfuseSettings` | `LANGFUSE_ENABLED` (true), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` |
| LLM Cache | `LLMCacheSettings` | `LLM_CACHE_ENABLED` (false), `LLM_CACHE_TTL_SECONDS` (3600) |
| Gradio UI | `GradioUISettings` | Layout params (`UI_CHAT_HEIGHT`, `UI_MSG_INPUT_LINES`, etc.), slider ranges, agent defaults (`UI_OBSERVER_DEFAULT_TEMP`, etc.) |

### 2.2 Валидация

Каждая группа содержит `@field_validator`-ы:

- Диапазоны: `REDIS_CACHE_PORT` ∈ [1, 65535], `APP_TZ_OFFSET` ∈ [-12, 14], `MAX_TURNS` ≥ 1, etc.
- Непустые строки: `REDIS_CACHE_HOST`, `LITELLM_BASE_URL`.
- Положительные значения: все timeout'ы, retry counts, backoff values.
- Нормализация путей: валидаторы `APP_LOG_DIR` и `INTERVIEW_LOG_DIR` вызывают только `resolve()` для приведения к абсолютному пути. Фактическое создание директорий (`mkdir(parents=True, exist_ok=True)`) происходит в отдельном методе `ensure_directories()`, а не во время валидации.
- Нормализация URL: `LITELLM_BASE_URL` и `LANGFUSE_HOST` — strip + rstrip("/").

### 2.3 Загрузка

```python
model_config = SettingsConfigDict(
    env_file=".env",
    case_sensitive=False,
    env_file_encoding="utf-8",
    extra="ignore",
    env_prefix="",
)
```

- Файл `.env` в корне проекта.
- `extra="ignore"` — неизвестные переменные не вызывают ошибку.
- `case_sensitive=False` — переменные окружения регистронезависимы.

### 2.4 Singleton

Экземпляр `Settings` создаётся лениво через функцию `get_settings()` с double-checked locking (проверка → блокировка → повторная проверка). Модуль `config.py` предоставляет атрибут `settings` через `__getattr__`-прокси, который при обращении вызывает `get_settings()`. Таким образом, экземпляр создаётся при первом доступе к `settings`, а не в момент импорта модуля. Все остальные модули импортируют `settings` из `core.config`.

---

## 3. Секреты

### 3.1 Перечень секретов

| Секрет | Переменная окружения | Назначение | Где используется |
|---|---|---|---|
| LiteLLM API key | `LITELLM_API_KEY` | Bearer token для аутентификации в LiteLLM proxy | `LLMClient` → HTTP заголовок `Authorization` |
| Langfuse public key | `LANGFUSE_PUBLIC_KEY` | Публичный ключ Langfuse API | `LangfuseTracker` → Langfuse SDK init |
| Langfuse secret key | `LANGFUSE_SECRET_KEY` | Секретный ключ Langfuse API | `LangfuseTracker` → Langfuse SDK init |
| Langfuse DB password | `LANGFUSE_DB_PASSWORD` | Пароль PostgreSQL для Langfuse | `docker-compose.yml` → Langfuse container |
| NextAuth secret | `LANGFUSE_NEXTAUTH_SECRET` | Секрет для NextAuth (Langfuse UI) | `docker-compose.yml` → Langfuse container |
| NextAuth salt | `LANGFUSE_SALT` | Соль для хеширования (Langfuse UI) | `docker-compose.yml` → Langfuse container |

### 3.2 Практики безопасности

- Секреты хранятся в `.env`, который включён в `.gitignore`.
- `.env.example` содержит шаблон без реальных значений.
- API key маскируется при логировании: `***{key[-4:]}` (последние 4 символа).
- `SENSITIVE_KEYS` (`src/app/core/constants.py`) — набор заголовков HTTP для маскирования при логировании: `authorization`, `api_key`, `secret`, `token`, `jwt`, etc.
- Langfuse SDK получает ключи при инициализации; если ключи пустые и `LANGFUSE_ENABLED=true` — трекинг отключается автоматически с логированием причины.

---

## 4. Запуск

### 4.1 Gradio UI (`Dockerfile.gradio`)

```text
ENTRYPOINT ["python", "-m", "app.gradio_main", "--host", "0.0.0.0", "--port", "7860"]
```

- CLI аргументы: `--host`, `--port`, `--share`.
- `setup_logging()` вызывается в `main()`.
- `create_gradio_interface()` строит Gradio `Blocks` с настройками из `GradioUISettings`.
- `launch_app()` вызывает `app.launch(server_name=..., server_port=..., share=...)`.

### 4.2 FastAPI Backend (`Dockerfile`)

```text
ENTRYPOINT ["sh", "-c",
  "total=$(nproc); reserve=$RESERVED_CPUS; workers=$((total > reserve ? total - reserve : 1));
   exec gunicorn -k uvicorn.workers.UvicornWorker --workers $workers --threads 2
   --worker-connections 1000 -b 0.0.0.0:$BACKEND_PORT --timeout 1200
   --graceful-timeout 600 app.main:app"]
```

- Количество воркеров: `nproc - RESERVED_CPUS` (минимум 1).
- `RESERVED_CPUS=6` (default в Dockerfile).
- Timeout: 1200s (20 мин) — для длинных LLM-вызовов.
- Graceful timeout: 600s (10 мин).

### 4.3 Lifespan (FastAPI)

Файл: `src/app/core/setup.py` → `lifespan_factory()`.

Startup:
1. `set_threadpool_tokens(100)` — ограничение параллелизма anyio.
2. `create_redis_cache_pool(redis_url)` — подключение к Redis.
3. `initialization_complete.set()` — сигнал готовности.

Shutdown:
1. `close_redis_cache_pool()` — закрытие Redis connection.
2. `shutdown_langfuse()` — graceful flush Langfuse tracker.

### 4.4 Docker Compose

| Сервис | Образ | Порт | Зависимости |
|---|---|---|---|
| `interview-coach` | `Dockerfile.gradio` | `${GRADIO_PORT:-7860}` | `redis_cache`, `langfuse` |
| `backend` | `Dockerfile` | `${BACKEND_PORT}` (internal) | `redis_cache`, `langfuse` |
| `redis_cache` | `redis:alpine` | `${REDIS_CACHE_PORT}` (internal) | — |
| `nginx` | `nginx:latest` | `${NGINX_EXTERNAL_PORT}` | `backend` |
| `langfuse` | `langfuse/langfuse:2` | `${LANGFUSE_PORT:-3000}` | `langfuse-db` (healthy) |
| `langfuse-db` | `postgres:15-alpine` | 5432 (internal) | — |

Volumes: `redis-cache-data`, `interview-logs`, `langfuse-db-data`.
Network: `internal` (bridge).

Restart policy: `on-failure:3` для всех сервисов.

---

## 5. Версии моделей

### 5.1 Конфигурация модели

Модель задаётся на двух уровнях:

1. **Глобально**: `LITELLM_MODEL` в `.env` (default: `local_llm`).
2. **На сессию**: пользователь выбирает модель в UI dropdown.

Приоритет: UI выбор > `LITELLM_MODEL` fallback.

### 5.2 Получение списка моделей

Файл: `src/app/llm/models.py`.

| Функция | Тип | Назначение |
|---|---|---|
| `fetch_available_models()` | async | `GET /v1/models` через `httpx.AsyncClient`, таймаут `LITELLM_MODELS_FETCH_TIMEOUT` |
| `fetch_available_models_sync()` | sync | То же, через `httpx.Client` (для инициализации UI) |
| `get_models_for_ui()` | sync | Обёртка с fallback на `[LITELLM_MODEL]` при ошибке |

### 5.3 Конфигурация LiteLLM proxy

Файл: `llm-gateway-litellm/config.yaml`.

```yaml
model_list:
  - model_name: local_llm
    litellm_params:
      model: ollama/model-name
      api_base: http://host.docker.internal:11434

  - model_name: cloud/deepseek-chat
    litellm_params:
      model: deepseek/deepseek-chat
      api_key: os.environ/DEEPSEEK_API_KEY

general_settings:
  store_model_in_db: true

litellm_settings:
  num_retries: 2
  allowed_fails: 3
  cooldown_time: 30
  request_timeout: 600
```

### 5.4 Маршрутизация

LiteLLM proxy принимает `model` из payload запроса и маршрутизирует к соответствующему бэкенду из `model_list`. При `store_model_in_db: true` модели также можно добавлять через LiteLLM UI/API.

---

## 6. Middleware

### 6.1 ClientCacheMiddleware

Файл: `src/app/middleware/client_cache_middleware.py`.

- Наследуется от `BaseHTTPMiddleware` (Starlette).
- Добавляет заголовок `Cache-Control: public, max-age={CLIENT_CACHE_MAX_AGE}` ко всем ответам FastAPI.
- Параметр `max_age` задаётся через `CLIENT_CACHE_MAX_AGE` (default: 60s).

### 6.2 Nginx

Файл: `default.conf`.

- Reverse proxy для FastAPI backend.
- Предназначен для блокировки `/docs`, `/redoc`, `/openapi.json` из внешнего доступа.
- Внутри Docker Compose network — сервис `nginx` проксирует к `backend`.

---

## 7. Документация API

Файл: `src/app/core/setup.py` → `create_application()`.

- Стандартные Swagger/Redoc маршруты отключены в FastAPI (`docs_url=None`, `redoc_url=None`, `openapi_url=None`).
- Пересозданы через отдельный `docs_router`:
  - `GET /docs` → Swagger UI.
  - `GET /redoc` → ReDoc.
  - `GET /openapi.json` → OpenAPI schema.
- Доступ ограничивается через Nginx (не на уровне приложения).

---

## 8. Health Checks

### 8.1 LLM API

- `LLMClient.check_health()` — `GET /health/readiness` к LiteLLM proxy.
- Таймаут: `LITELLM_HEALTH_CHECK_TIMEOUT` (default: 5s).
- Вызывается перед `InterviewSession.start()`.
- При неуспехе — сессия не создаётся, пользователь получает сообщение об ошибке.

### 8.2 Docker

- `langfuse-db`: `pg_isready` каждые 5s, 5 retries.
- `langfuse`: зависит от `langfuse-db` (`condition: service_healthy`).
- Все сервисы: `restart: on-failure:3`.

---

## 9. Переменные окружения — полный справочник

### LiteLLM

| Переменная | Тип | Default | Описание |
|---|---|---|---|
| `LITELLM_BASE_URL` | str | `http://localhost:4000` | Базовый URL LiteLLM proxy |
| `LITELLM_API_KEY` | str \| None | `None` | API ключ |
| `LITELLM_MODEL` | str | `local_llm` | Модель по умолчанию |
| `LITELLM_TIMEOUT` | int | `120` | Таймаут запросов (секунды) |
| `LITELLM_MAX_RETRIES` | int | `3` | Максимум повторных попыток |
| `LITELLM_RETRY_BACKOFF_BASE` | float | `0.5` | Базовая задержка backoff |
| `LITELLM_RETRY_BACKOFF_MAX` | float | `30.0` | Максимальная задержка backoff |
| `LITELLM_MODELS_FETCH_TIMEOUT` | float | `10.0` | Таймаут получения списка моделей |
| `LITELLM_HEALTH_CHECK_TIMEOUT` | float | `5.0` | Таймаут health check |
| `LITELLM_CIRCUIT_BREAKER_THRESHOLD` | int | `5` | Порог circuit breaker |
| `LITELLM_CIRCUIT_BREAKER_RECOVERY` | float | `60.0` | Таймаут восстановления circuit breaker |

### Интервью

| Переменная | Тип | Default | Описание |
|---|---|---|---|
| `INTERVIEW_LOG_DIR` | Path | `./interview_logs` | Директория логов интервью |
| `TEAM_NAME` | str | `Interview Coach Team` | Имя команды |
| `MAX_TURNS` | int | `20` | Лимит ходов |
| `HISTORY_WINDOW_TURNS` | int | `10` | Окно истории для Interviewer |
| `GREETING_MAX_TOKENS` | int | `300` | Макс. токенов для приветствия |

### Redis

| Переменная | Тип | Default | Описание |
|---|---|---|---|
| `REDIS_CACHE_HOST` | str | `localhost` | Хост Redis |
| `REDIS_CACHE_PORT` | int | `6379` | Порт Redis |

### Langfuse

| Переменная | Тип | Default | Описание |
|---|---|---|---|
| `LANGFUSE_ENABLED` | bool | `true` | Включить трекинг |
| `LANGFUSE_PUBLIC_KEY` | str \| None | `None` | Публичный ключ |
| `LANGFUSE_SECRET_KEY` | str \| None | `None` | Секретный ключ |
| `LANGFUSE_HOST` | str | `http://localhost:3000` | URL хоста Langfuse |

### Приложение

| Переменная | Тип | Default | Описание |
|---|---|---|---|
| `APP_NAME` | str | `FastAPI app` | Имя приложения |
| `APP_DESCRIPTION` | str | `None` | Описание |
| `APP_VERSION` | str | `None` | Версия |
| `APP_TZ_OFFSET` | int | `3` | Смещение TZ для логов |
| `APP_LOG_DIR` | Path | `./logs` | Директория логов |
| `LOG_MAX_BYTES` | int | `10485760` | Макс. размер лог-файла |
| `LOG_BACKUP_COUNT` | int | `2` | Количество backup'ов |
| `CLIENT_CACHE_MAX_AGE` | int | `60` | Cache-Control max-age |
| `ENVIRONMENT` | enum | `local` | Окружение (local/staging/production) |