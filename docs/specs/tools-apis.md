# Spec: Tools / APIs — Multi-Agent Interview Coach

Техническая спецификация внешних интеграций, контрактов, обработки ошибок и защитных механизмов.

---

## 1. LiteLLM Proxy (основная интеграция)

### 1.1 Контракт

| Параметр | Значение |
|---|---|
| Протокол | HTTP/1.1, JSON body |
| Base URL | `LITELLM_BASE_URL` (default: `http://localhost:4000`) |
| Аутентификация | `Authorization: Bearer {LITELLM_API_KEY}` |
| Content-Type | `application/json` |

### 1.2 Используемые endpoints

#### `POST /v1/chat/completions`

Основной endpoint для генерации ответов LLM.

**Запрос:**

```json
{
  "model": "string",
  "messages": [
    {"role": "system", "content": "string"},
    {"role": "user", "content": "string"},
    {"role": "assistant", "content": "string"}
  ],
  "temperature": 0.0,
  "max_tokens": 4096,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "string",
      "schema": {"type": "object"}
    }
  }
}
```

Поле `response_format` — опциональное, используется только при `json_mode=True` в `LLMClient.complete()`. При HTTP 400 (модель не поддерживает `response_format`) автоматически переключается на текстовый режим. Состояние кэшируется: после первого отказа все последующие вызовы используют текстовый режим.

**Ответ (2xx):**

```json
{
  "choices": [
    {
      "message": {
        "content": "string"
      }
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

**Заголовки ответа:**

| Заголовок | Описание |
|---|---|
| `x-litellm-response-cost` | Стоимость вызова в USD (float). Для локальных моделей без настроенного прайсинга — `0.0` или отсутствует. |

**Обработка ошибок:**

| HTTP код | Поведение |
|---|---|
| 200 | Успех → parse response, extract content, usage, cost |
| 400 | Если связана с `response_format` → fallback на текстовый режим. Иначе → `LLMClientError` (без retry) |
| 401, 403 | `LLMClientError` (без retry, ошибка аутентификации) |
| 429 | Rate limit → retry с exponential backoff |
| 500, 502, 503, 504 | Server error → retry с exponential backoff |

Retryable HTTP codes определены в `_RETRYABLE_HTTP_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})`.

#### `GET /v1/models`

Получение списка доступных моделей для UI.

**Ответ:**

```json
{
  "data": [
    {"id": "model_name_1"},
    {"id": "model_name_2"}
  ]
}
```

Используется в `fetch_available_models()` (async) и `fetch_available_models_sync()` (sync). При любой ошибке — возвращается пустой список, UI использует fallback на `LITELLM_MODEL`.

#### `GET /health/readiness`

Проверка готовности LiteLLM proxy перед стартом сессии.

| Параметр | Значение |
|---|---|
| Таймаут | `LITELLM_HEALTH_CHECK_TIMEOUT` (default: 5s) |
| Успех | HTTP 200 |
| Неудача | Любой другой статус, таймаут, сетевая ошибка |

При неудаче — сессия не создаётся, пользователь получает сообщение `"LLM API is not available"`.

### 1.3 Timeout

| Параметр | Значение по умолчанию | Настройка |
|---|---|---|
| Таймаут запроса | 120s | `LITELLM_TIMEOUT` |
| Health check таймаут | 5s | `LITELLM_HEALTH_CHECK_TIMEOUT` |
| Fetch models таймаут | 10s | `LITELLM_MODELS_FETCH_TIMEOUT` |

### 1.4 Retry

| Параметр | Значение по умолчанию | Настройка |
|---|---|---|
| Максимум попыток | 3 | `LITELLM_MAX_RETRIES` |
| Базовая задержка backoff | 0.5s | `LITELLM_RETRY_BACKOFF_BASE` |
| Максимальная задержка backoff | 30s | `LITELLM_RETRY_BACKOFF_MAX` |
| Формула задержки | `min(base × 2^attempt, max)` | — |

Retry применяется к HTTP кодам из `_RETRYABLE_HTTP_CODES` и к `httpx.TimeoutException` / `httpx.RequestError`.

### 1.5 Circuit Breaker

| Параметр | Значение по умолчанию | Настройка |
|---|---|---|
| Порог сбоев | 5 consecutive failures | `LITELLM_CIRCUIT_BREAKER_THRESHOLD` |
| Время восстановления | 60s | `LITELLM_CIRCUIT_BREAKER_RECOVERY` |
| Состояния | CLOSED → OPEN → HALF_OPEN → CLOSED | — |

Реализован в `CircuitBreaker` (`src/app/llm/circuit_breaker.py`). Singleton через `_get_shared_circuit_breaker()` — общий для всех `LLMClient` экземпляров.

**Переходы состояний:**

- `CLOSED → OPEN`: после `failure_threshold` последовательных сбоев (все retry исчерпаны).
- `OPEN → HALF_OPEN`: автоматически через `recovery_timeout` секунд.
- `HALF_OPEN → CLOSED`: при успешном запросе.
- `HALF_OPEN → OPEN`: при неуспешном запросе.

При состоянии `OPEN` запросы отклоняются немедленно с `CircuitBreakerOpen`, который проксируется как `LLMClientError`.

### 1.6 Side effects

| Side effect | Описание |
|---|---|
| Потребление токенов | Каждый вызов расходует токены у LLM-провайдера. Стоимость трекается через `x-litellm-response-cost`. |
| Логирование LiteLLM | LiteLLM proxy записывает запросы в свою БД (PostgreSQL) при `STORE_MODEL_IN_DB=true`. |
| Langfuse generation | Каждый вызов `complete()` создаёт Langfuse `generation` с input messages, output, usage, cost. |
| SessionMetrics | Каждый успешный вызов обновляет `SessionMetrics` (токены по агентам, стоимость). |

### 1.7 Защита

| Мера | Реализация |
|---|---|
| Маскирование API key | В логах отображается `***{key[-4:]}` |
| `<user_input>` обёртка | Пользовательский текст передаётся в XML-теге с инструкцией игнорировать команды |
| Circuit breaker | Защита от каскадных retry при длительной недоступности |
| Health check | Проверка перед созданием сессии, предотвращает бесполезные попытки |
| Не-retryable 4xx | HTTP 4xx (кроме 429) не считаются сбоем сервиса и не влияют на circuit breaker |

---

## 2. Langfuse (observability)

### 2.1 Контракт

| Параметр | Значение |
|---|---|
| Протокол | HTTP (Langfuse Python SDK) |
| Host | `LANGFUSE_HOST` (default: `http://localhost:3000`) |
| Аутентификация | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` |
| Режим | Async batch flush |

### 2.2 Используемые сущности

| Сущность | Когда создаётся | Данные |
|---|---|---|
| **Trace** | `InterviewSession.start()` | name=`interview_session`, session_id, metadata (model, max_turns, has_job_description) |
| **Generation** | Каждый `LLMClient.complete()` | name (observer_analysis / interviewer_response / interviewer_greeting / evaluator_feedback), model, input_messages, output, usage, cost_usd, metadata (temperature, max_tokens, json_mode) |
| **Span** | Ключевые этапы пайплайна | greeting, user_message, observer_analysis, interviewer_response, candidate_info_update, difficulty_change, final_feedback, session_token_metrics |
| **Score** | `generate_feedback()` | total_tokens, total_turns, llm_calls, avg_tokens_per_turn, confidence_score, session_cost_usd |

### 2.3 Обработка ошибок

| Сценарий | Поведение |
|---|---|
| `LANGFUSE_ENABLED=false` | Все вызовы `LangfuseTracker` → no-op. Бизнес-логика не затрагивается. |
| Ключи не заданы | Трекинг автоматически отключается при инициализации (логируется warning). |
| Сетевая ошибка | SDK обрабатывает внутренне (async batch), не влияет на основной пайплайн. |
| Langfuse недоступен | Данные теряются (нет retry на уровне приложения). SDK буферизирует и пытается переотправить. |

### 2.4 Timeout

Управляется SDK Langfuse (не настраивается на уровне приложения). При длительной недоступности — данные теряются.

### 2.5 Side effects

| Side effect | Описание |
|---|---|
| Запись в PostgreSQL | Трейсы, генерации, span'ы и score'ы сохраняются в БД Langfuse. |
| Передача PII | Имя кандидата передаётся как `user_id` трейса. Текст сообщений — в input/output генераций и span'ов. |

### 2.6 Защита

- При `LANGFUSE_ENABLED=false` данные не передаются.
- Self-hosted deployment — данные не покидают периметр инфраструктуры.
- Graceful shutdown: `LangfuseTracker.shutdown()` вызывается в lifespan FastAPI.

---

## 3. Redis

### 3.1 Контракт

| Параметр | Значение |
|---|---|
| Протокол | TCP (Redis wire protocol) |
| URL | `redis://{REDIS_CACHE_HOST}:{REDIS_CACHE_PORT}` |
| Библиотека | `redis.asyncio` |
| Lifecycle | Connection pool создаётся в lifespan FastAPI, закрывается при shutdown |

### 3.2 Использование

Redis используется в двух независимых контекстах:

1. **General-purpose cache** — `src/app/utils/cache.py`. Используется FastAPI backend для кэширования произвольных данных. Connection pool создаётся в lifespan FastAPI, закрывается при shutdown.

2. **LLM response cache** — `src/app/llm/cache.py` (`RedisLLMCache` / `NullLLMCache`). Используется `LLMClient` для кэширования ответов LLM как в Gradio UI, так и в FastAPI backend процессах. Ключ кэша — SHA-256 от параметров запроса (model, messages, temperature, max_tokens, json_mode). Подключение ленивое (lazy connection при первом обращении). При недоступности Redis деградирует gracefully — переключается на `NullLLMCache` (no-op), запросы идут напрямую к LLM без кэширования. TTL настраивается через `LLM_CACHE_TTL_SECONDS`.

### 3.3 Обработка ошибок

| Сценарий | Поведение |
|---|---|
| Redis недоступен при старте | Lifespan FastAPI не завершает инициализацию (приложение не стартует). |
| Redis недоступен в runtime | Операции кэширования завершаются с ошибкой. Основная логика интервью (Gradio UI) не затрагивается. |

### 3.4 Защита

- Connection pool ограничивает количество подключений.
- `is_redis_connected()` — проверка перед операциями.
- `clear_redis_connection()` — явное освобождение ресурсов при shutdown.

---

## 4. Nginx (reverse proxy)

### 4.1 Контракт

| Параметр | Значение |
|---|---|
| Протокол | HTTP/1.1 |
| Конфигурация | `default.conf` |
| Upstream | Контейнер `backend` на порту `${BACKEND_PORT}` |
| Внешний порт | `${NGINX_EXTERNAL_PORT}` |

### 4.2 Защита

- Блокировка `/docs`, `/redoc`, `/openapi.json` извне (на уровне конфигурации Nginx).
- `ClientCacheMiddleware` добавляет `Cache-Control: public, max-age={CLIENT_CACHE_MAX_AGE}`.

---

## 5. Файловая система (логирование)

### 5.1 Контракт

| Хранилище | Формат | Путь | Ротация |
|---|---|---|---|
| Application logs | Text (formatted) | `{APP_LOG_DIR}/system.log`, `{APP_LOG_DIR}/personal.log` | `RotatingFileHandler`: `LOG_MAX_BYTES` (10 MB), `LOG_BACKUP_COUNT` (2) |
| Interview logs | JSON | `{INTERVIEW_LOG_DIR}/interview_log_*.json` | Нет автоматической ротации. Каждая сессия — отдельный файл. |
| Detailed logs | JSON | `{INTERVIEW_LOG_DIR}/interview_detailed_*.json` | Нет автоматической ротации. Каждая сессия — отдельный файл. |

### 5.2 Обработка ошибок

| Сценарий | Поведение |
|---|---|
| Директория не существует | Создаётся автоматически при валидации `Settings` (field_validator). |
| Ошибка записи | `_save_metrics_to_log()` — ловит `Exception`, логирует ошибку, не прерывает основной поток. `save_session()` / `save_raw_log()` — исключение пробрасывается. |

### 5.3 Защита

- Пути логов конфигурируются через `.env`, не hardcoded.
- Директории создаются с `parents=True, exist_ok=True`.
- `SENSITIVE_KEYS` — набор ключей HTTP-заголовков для маскирования.
- API key маскируется в логах: `***{key[-4:]}`.