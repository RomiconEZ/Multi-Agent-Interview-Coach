# System Design — Multi-Agent Interview Coach

Документ описывает архитектуру системы, ключевые решения, модули, workflow, управление состоянием, retrieval-контур, интеграции, failure modes и операционные ограничения.

---

## 1. Ключевые архитектурные решения

### 1.1 Мультиагентная декомпозиция

Система разделена на три специализированных агента вместо одного монолитного LLM-вызова:

| Агент | Ответственность | Обоснование изоляции |
|---|---|---|
| **Observer** | Классификация ответа, факт-чекинг, извлечение данных кандидата | Требует низкую temperature (0.3), структурированный JSON-вывод, retry при ошибках парсинга |
| **Interviewer** | Генерация реплик, ведение диалога, адаптация вопросов | Требует высокую temperature (0.7), свободный текстовый вывод, без retry |
| **Evaluator** | Финальный структурированный фидбэк | Требует низкую temperature (0.3), сложную JSON-схему, retry при ошибках парсинга |

Каждый агент имеет изолированный системный промпт, собственную конфигурацию (`SingleAgentConfig`: temperature, max_tokens, generation_retries) и отдельный формат вывода.

### 1.2 Атомарность мутаций состояния

Неидемпотентные изменения (`knowledge_gaps`, `confirmed_skills`, `covered_topics`, счётчик ходов) применяются **только после полного успеха** цепочки Observer → Interviewer. При сбое Interviewer корректировка сложности откатывается к сохранённому snapshot. Это гарантирует консистентность `InterviewState` при повторной отправке сообщения.

### 1.3 Активный якорь (один вопрос)

В интервью всегда существует ровно один активный технический вопрос. Система хранит `_last_agent_message` как якорь. Observer определяет `answered_last_question`, а Interviewer обязан возвращаться к якорю при off-topic, встречных вопросах, бессмыслице и галлюцинациях не по теме.

### 1.4 LLM через прокси (LiteLLM)

Приложение не обращается к LLM-провайдерам напрямую. Все запросы идут через LiteLLM proxy (`/v1/chat/completions`), что даёт:

- единый OpenAI-compatible API для любых бэкендов (локальные модели, DeepSeek, OpenAI);
- маршрутизацию, балансировку, fallback между моделями на уровне прокси;
- учёт стоимости через заголовок `x-litellm-response-cost`;
- централизованное управление моделями через `config.yaml` и БД.

### 1.5 Observability как first-class citizen

Langfuse (self-hosted) интегрирован на уровне каждого LLM-вызова и каждого этапа пайплайна. Трейсы, генерации, span'ы и score'ы создаются автоматически. При отключении (`LANGFUSE_ENABLED=false`) все вызовы становятся no-op без изменения бизнес-логики.

### 1.6 In-memory состояние

Состояние сессии (`InterviewState`, `SessionMetrics`) хранится в памяти процесса. Это осознанное решение для MVP: простота, отсутствие зависимости от внешнего хранилища для горячих данных. Персистентность обеспечивается сохранением JSON-логов на диск при завершении сессии.

---

## 2. Список модулей и их роли

### 2.1 Presentation Layer

| Модуль | Путь | Роль |
|---|---|---|
| **Gradio UI** | `src/app/ui/gradio_app.py` | Веб-интерфейс: чат, настройки, фидбэк. Двухшаговый паттерн отправки сообщений (instant UI update + async LLM). |
| **Styles** | `src/app/ui/styles.py` | CSS-стили и HTML-разметка хедера. |
| **Gradio Entry** | `src/app/gradio_main.py` | CLI точка входа для запуска Gradio-сервера. |
| **FastAPI App** | `src/app/main.py` | Точка входа FastAPI backend (docs, middleware, Redis lifespan). |

### 2.2 Orchestration Layer

| Модуль | Путь | Роль |
|---|---|---|
| **InterviewSession** | `src/app/interview/session.py` | Оркестратор: lifecycle сессии, последовательный вызов агентов, атомарные мутации, адаптация сложности, интеграция с Langfuse. |
| **InterviewLogger** | `src/app/interview/logger.py` | Сохранение основного и детального логов интервью в JSON. |

### 2.3 Agent Layer

| Модуль | Путь | Роль |
|---|---|---|
| **BaseAgent** | `src/app/agents/base.py` | Абстрактный базовый класс: `system_prompt`, `_build_messages()`, `_build_job_description_block()`. |
| **ObserverAgent** | `src/app/agents/observer.py` | Анализ ответа: классификация, факт-чекинг, извлечение данных, рекомендации. |
| **InterviewerAgent** | `src/app/agents/interviewer.py` | Генерация реплик: приветствие, вопросы, обработка сценариев (gibberish, hallucination, off-topic, question). |
| **EvaluatorAgent** | `src/app/agents/evaluator.py` | Финальный фидбэк: вердикт, техобзор, soft skills, роадмап. |
| **Prompts** | `src/app/agents/prompts/*.py` | Системные промпты агентов (constants `Final[str]`). |

### 2.4 LLM Integration Layer

| Модуль | Путь | Роль |
|---|---|---|
| **LLMClient** | `src/app/llm/client.py` | HTTP-клиент к LiteLLM proxy: retry с exponential backoff, circuit breaker, health check, Langfuse generation tracking, cost extraction. |
| **CircuitBreaker** | `src/app/llm/circuit_breaker.py` | Паттерн Circuit Breaker (CLOSED → OPEN → HALF_OPEN) для защиты от каскадных сбоев. |
| **ResponseParser** | `src/app/llm/response_parser.py` | Многоуровневый парсер JSON из ответов LLM: `<r>` → `<result>` → markdown code block → raw `{...}`. |
| **Models** | `src/app/llm/models.py` | Получение списка моделей из LiteLLM `/v1/models` (async + sync). |

### 2.5 Observability Layer

| Модуль | Путь | Роль |
|---|---|---|
| **LangfuseTracker** | `src/app/observability/langfuse_client.py` | Фасад над Langfuse SDK: trace, generation, span, score. Singleton. |
| **SessionMetrics** | `src/app/observability/langfuse_client.py` | Агрегатор метрик: токены по агентам, стоимость, среднии значения. |
| **TokenUsage** | `src/app/observability/langfuse_client.py` | Структура подсчёта input/output/total токенов и стоимости. |

### 2.6 Core Infrastructure

| Модуль | Путь | Роль |
|---|---|---|
| **Config** | `src/app/core/config.py` | Pydantic-settings: 9 групп настроек, валидация, computed fields. |
| **LoggerSetup** | `src/app/core/logger_setup.py` | TZ-aware форматтеры, system/personal фильтры, RotatingFileHandler. |
| **Setup** | `src/app/core/setup.py` | FastAPI factory: lifespan (Redis, Langfuse, threadpool), middleware, docs router. |
| **Constants** | `src/app/core/constants.py` | `SENSITIVE_KEYS`, `REQUEST_ID_PATTERN`. |
| **Exceptions** | `src/app/core/exceptions/` | `CustomException(HTTPException)`, cache-specific exceptions. |

### 2.7 Data Layer

| Модуль | Путь | Роль |
|---|---|---|
| **Schemas: Interview** | `src/app/schemas/interview.py` | `InterviewState`, `InterviewTurn`, `ObserverAnalysis`, `CandidateInfo`, enums (`ResponseType`, `DifficultyLevel`, etc.). |
| **Schemas: Feedback** | `src/app/schemas/feedback.py` | `InterviewFeedback`, `Verdict`, `TechnicalReview`, `SoftSkillsReview`, `PersonalRoadmap`, `InterviewLog`. |
| **Schemas: Agent Settings** | `src/app/schemas/agent_settings.py` | `SingleAgentConfig`, `AgentSettings`, `InterviewConfig`. |
| **Redis Cache** | `src/app/utils/cache.py` | Connection pool и клиент Redis (для FastAPI backend). |

### 2.8 Middleware

| Модуль | Путь | Роль |
|---|---|---|
| **ClientCacheMiddleware** | `src/app/middleware/client_cache_middleware.py` | Добавляет `Cache-Control: public, max-age=...` к ответам FastAPI. |

---

## 3. Основной workflow выполнения задачи

### 3.1 Старт сессии

```text
User → [Нажать «Начать интервью»]
  → Gradio UI: _start_interview_async()
    → create_interview_session(config)
      → create_llm_client(model)
      → create_interview_logger()
    → InterviewSession.start()
      → LLMClient.check_health()          # GET /health/readiness
      → InterviewState(job_description=...) # in-memory state
      → LangfuseTracker.create_trace()     # trace на сессию
      → InterviewerAgent.generate_greeting()
        → LLMClient.complete()             # LLM call #1
      → InterviewTurn(greeting)
      → LangfuseTracker.add_span("greeting")
    → return greeting
```

### 3.2 Обработка сообщения (один ход)

```text
User → [Отправить сообщение]
  → add_user_message()       # Шаг 1: sync, queue=False — instant UI update
  → bot_respond()            # Шаг 2: async generator — LLM processing
    → InterviewSession.process_message(user_message)

      ┌─ Stage 1: Observer ──────────────────────────────────────────┐
      │ ObserverAgent.process(state, user_message, last_question)    │
      │   → LLMClient.complete() → JSON → ObserverAnalysis          │
      │   → LangfuseTracker.add_span("observer_analysis")           │
      │   [при ошибке → return error message, NO state mutation]     │
      └──────────────────────────────────────────────────────────────┘

      ┌─ Stage 2: Идемпотентное обновление ──────────────────────────┐
      │ _update_candidate_info(extracted_info)                       │
      │   → CandidateInfo: name, position, grade, experience, techs  │
      │   [идемпотентно: поле обновляется только если текущее = None] │
      └──────────────────────────────────────────────────────────────┘

      ┌─ Stage 3: Стоп-команда ──────────────────────────────────────┐
      │ if STOP_COMMAND → is_active = False → return, trigger feedback│
      └──────────────────────────────────────────────────────────────┘

      ┌─ Stage 4: Корректировка сложности ───────────────────────────┐
      │ [snapshot: saved_difficulty, saved_good_streak, saved_bad]    │
      │ if answered_last_question:                                   │
      │   state.adjust_difficulty(analysis)                          │
      │ else: skip (нельзя менять сложность без ответа)              │
      └──────────────────────────────────────────────────────────────┘

      ┌─ Stage 5: Interviewer ───────────────────────────────────────┐
      │ InterviewerAgent.process(state, analysis, user_message)      │
      │   → LLMClient.complete() → (response_text, thoughts)        │
      │   [при ошибке → ROLLBACK difficulty → return error message]  │
      └──────────────────────────────────────────────────────────────┘

      ┌─ Stage 6: Фиксация (только при полном успехе) ───────────────┐
      │ increment_turn()                                             │
      │ _update_state_from_analysis() → topics, skills, gaps         │
      │ _last_agent_message = response                               │
      │ InterviewTurn(response)                                      │
      │ LangfuseTracker.add_span("interviewer_response")             │
      └──────────────────────────────────────────────────────────────┘

    → yield (status, history, feedback, ...)
```

### 3.3 Завершение и генерация фидбэка

```text
[STOP_COMMAND | MAX_TURNS | кнопка «Завершить»]
  → InterviewSession.generate_feedback()
    → EvaluatorAgent.process(state)
      → LLMClient.complete() → JSON → InterviewFeedback
    → LangfuseTracker.add_span("final_feedback")
    → LangfuseTracker.score_trace("confidence_score", ...)
    → LangfuseTracker.add_session_metrics_to_trace()
    → LangfuseTracker.flush()
    → InterviewLogger.save_session() → interview_log_*.json
    → InterviewLogger.save_raw_log()  → interview_detailed_*.json
    → _save_metrics_to_log()          → token_metrics в детальный лог
    → return (feedback, summary_path, detailed_path)
```

---

## 4. State / Memory / Context Handling

### 4.1 Состояние сессии (InterviewState)

Хранится in-memory как Pydantic `BaseModel`:

```text
InterviewState
  ├── candidate: CandidateInfo      # name, position, grade, experience, technologies
  ├── job_description: str | None   # описание вакансии
  ├── turns: list[InterviewTurn]    # история ходов
  ├── current_turn: int             # счётчик ходов
  ├── current_difficulty: DifficultyLevel  # BASIC → EXPERT
  ├── covered_topics: list[str]     # затронутые темы
  ├── confirmed_skills: list[str]   # подтверждённые навыки
  ├── knowledge_gaps: list[dict]    # выявленные пробелы
  ├── is_active: bool               # активна ли сессия
  ├── consecutive_good_answers: int # streak хороших ответов
  └── consecutive_bad_answers: int  # streak плохих ответов
```

**Lifecycle**: создаётся при `InterviewSession.start()`, мутируется при каждом `process_message()`, персистируется в JSON при `generate_feedback()`. Теряется при аварийном завершении процесса до вызова `generate_feedback()`.

### 4.2 Контекстный бюджет LLM

| Агент | Что получает в контекст | Ограничение |
|---|---|---|
| **Observer** | Системный промпт + резюме последних 5 ходов (обрезка 100 символов/реплику) + текущее сообщение | Компактный контекст, ~2–3K токенов |
| **Interviewer** | Системный промпт + полная история последних `HISTORY_WINDOW_TURNS` ходов (по умолчанию 10) + контекст из Observer | Растёт линейно с длиной сессии, ограничен window |
| **Evaluator** | Системный промпт + полная история всех ходов + skills summary | Максимальный контекст, ~6–10K токенов |

### 4.3 Адаптация сложности

Детерминированный алгоритм в `InterviewState.adjust_difficulty()`:

- `should_increase_difficulty` → `consecutive_good_answers += 1`; при streak ≥ 2 → difficulty +1.
- `should_simplify` → `consecutive_bad_answers += 1`; при streak ≥ 2 → difficulty -1.
- Ни то, ни другое → streak сбрасывается.
- **Инвариант**: если `answered_last_question = false` → оба флага принудительно `false`.

### 4.4 Memory policy

- **Short-term memory**: `InterviewState` в памяти процесса.
- **Long-term memory**: JSON-логи на файловой системе (`INTERVIEW_LOG_DIR`).
- **Observability memory**: Langfuse PostgreSQL (трейсы, генерации, метрики).
- **Нет cross-session memory**: каждая сессия независима, нет профиля пользователя.

---

## 5. Retrieval-контур

В текущей архитектуре **отсутствует классический RAG-контур** (нет векторной базы, нет индексов, нет поиска по документам). Retrieval-подобные механизмы реализованы на уровне детерминированной логики:

### 5.1 Источники контекста для агентов

| Источник | Механизм | Агенты |
|---|---|---|
| История диалога | `InterviewState.get_conversation_history(window)` — последние N ходов | Interviewer |
| Резюме истории | `ObserverAgent._summarize_history()` — обрезка до 100 символов/реплику, 5 ходов | Observer |
| Навыки и пробелы | `InterviewState.confirmed_skills`, `knowledge_gaps` — накопленные за сессию | Evaluator |
| Информация о кандидате | `CandidateInfo` — извлечённые Observer'ом данные | Все агенты |
| Описание вакансии | `job_description` — пользовательский ввод, передаётся в контекст всех агентов | Все агенты |

### 5.2 Reranking

Не применяется. Контекст формируется детерминированно.

### 5.3 Ограничения

- Нет внешнего источника истины для верификации фактов Observer'ом — LLM полагается на свои знания.
- Нет доступа к актуальной документации технологий — возможны устаревшие `correct_answer`.

---

## 6. Tool / API интеграции

### 6.1 LiteLLM Proxy (основная интеграция)

| Параметр | Значение |
|---|---|
| Протокол | HTTP, OpenAI-compatible API |
| Endpoints | `POST /v1/chat/completions`, `GET /v1/models`, `GET /health/readiness` |
| Аутентификация | Bearer token (`LITELLM_API_KEY`) |
| Таймаут | `LITELLM_TIMEOUT` (default: 120s) |
| Retry | До `LITELLM_MAX_RETRIES` (default: 3), exponential backoff 0.5–30s |
| Retryable HTTP codes | 429, 500, 502, 503, 504 |
| Circuit breaker | OPEN после 5 consecutive failures, recovery через 60s |
| Health check | `GET /health/readiness` с таймаутом 5s перед стартом сессии |
| Cost tracking | Заголовок `x-litellm-response-cost` |

**Контракт запроса:**
```json
{
  "model": "string",
  "messages": [{"role": "system|user|assistant", "content": "string"}],
  "temperature": 0.0-2.0,
  "max_tokens": 64-8192,
  "response_format": {"type": "json_schema", ...}  // опционально
}
```

**Контракт ответа:**
```json
{
  "choices": [{"message": {"content": "string"}}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

**Side effects**: потребление токенов у LLM-провайдера, запись в логи LiteLLM.

### 6.2 Langfuse (observability)

| Параметр | Значение |
|---|---|
| Протокол | HTTP (Langfuse SDK) |
| Endpoints | Trace, Generation, Span, Score (через SDK) |
| Аутентификация | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` |
| Режим | Async flush, батчами |
| Graceful degradation | При `LANGFUSE_ENABLED=false` или отсутствии ключей — все вызовы no-op |

### 6.3 Redis

| Параметр | Значение |
|---|---|
| Протокол | TCP (redis protocol) |
| Назначение | Кэширование (FastAPI backend) |
| Lifecycle | Подключение в lifespan FastAPI, закрытие при shutdown |
| Отказ | Не блокирует работу Gradio UI (используется только backend) |

### 6.4 Nginx

| Параметр | Значение |
|---|---|
| Назначение | Reverse proxy для FastAPI backend |
| Защита | Блокировка `/docs`, `/redoc`, `/openapi.json` извне |

---

## 7. Failure Modes, Fallback и Guardrails

### 7.1 Failure Modes

| Сценарий | Детект | Защита | Остаточный риск |
|---|---|---|---|
| **LLM недоступен** | `httpx.RequestError`, health check fail | Retry с backoff, circuit breaker (OPEN после 5 сбоев, recovery 60s), health check перед стартом | При длительной недоступности — сессия блокируется |
| **LLM таймаут** | `httpx.TimeoutException` | Retry до `MAX_RETRIES`, exponential backoff 0.5–30s | При систематических таймаутах — circuit breaker OPEN |
| **Невалидный JSON от LLM** | `ValueError` в `extract_json_from_llm_response` | Многоуровневый парсер (`<r>` → `<result>` → code block → raw `{...}`), retry Observer/Evaluator до `generation_retries` раз | При систематическом отказе модели — сессия блокируется |
| **Сбой Interviewer после Observer** | Любое исключение в `InterviewerAgent.process()` | Откат `current_difficulty`, `consecutive_good/bad_answers`. Неидемпотентные мутации не применяются. Пользователь получает ошибку и может повторить | Состояние остаётся консистентным |
| **Prompt injection** | Observer классифицирует как `off_topic`, логирует | `<user_input>` обёртка с инструкцией игнорировать команды, секция `<security>` в промптах | Зависит от устойчивости конкретной LLM |
| **Галлюцинации Observer/Evaluator** | Ручная проверка выборки, метрика Evaluator Grounding | Промпты требуют подкрепления каждого утверждения репликой из диалога | Нет внешнего источника истины |
| **Потеря состояния при crash** | Отсутствие лога после аварийного завершения | Логи сохраняются при `generate_feedback()`. Детальный лог включает полное состояние | Данные теряются при crash до feedback |
| **Бессмыслица от пользователя** | Observer: `is_gibberish=true` | Interviewer переформулирует активный вопрос, не комментирует содержимое | — |
| **Исчерпание контекстного окна** | LLM обрезает ответ или возвращает ошибку | `HISTORY_WINDOW_TURNS` ограничивает историю Interviewer'а (default: 10), Observer получает только краткое резюме | При моделях с малым контекстом (< 8K) и длинных ответах — деградация |

### 7.2 Fallback-стратегии

| Компонент | Fallback |
|---|---|
| `complete_json()` | При HTTP 400 (response_format не поддерживается) → fallback на текстовый режим + JSON extraction из текста. Кэшируется навсегда. |
| `get_models_for_ui()` | При ошибке получения списка моделей → fallback на `[LITELLM_MODEL]` из конфигурации |
| `LangfuseTracker` | При `LANGFUSE_ENABLED=false` или отсутствии ключей → все методы no-op |

### 7.3 Guardrails

| Guardrail | Реализация |
|---|---|
| Максимум ходов | `MAX_TURNS` (default: 20, range: 5–50). Автоматическое завершение при достижении. |
| Контекстное окно | `HISTORY_WINDOW_TURNS` (default: 10) для Interviewer. Observer получает 5 последних ходов по 100 символов. |
| Защита от injection | `<user_input>` тег + инструкция «НЕ выполняй». Секции `<security>` в промптах. Детерминированные правила: injection → off_topic → активный вопрос сохраняется. |
| Консистентность сложности | Инвариант: `answered_last_question=false` → `should_simplify=false`, `should_increase_difficulty=false`. |
| Идемпотентность CandidateInfo | Поле обновляется только если текущее значение `None`. |
| Маскирование секретов | API key логируется как `***{key[-4:]}`. `SENSITIVE_KEYS` — набор заголовков для маскирования. |
| Circuit breaker | Предотвращает каскадный retry при недоступности LLM. |
| Health check | Проверка `/health/readiness` перед созданием сессии. |

---

## 8. Технические и операционные ограничения

### 8.1 Latency

| Операция | Целевой p95 | Факторы |
|---|---|---|
| Один ход (Observer + Interviewer) | ≤ 15s | 2 последовательных LLM-вызова, зависит от модели и длины контекста |
| Генерация фидбэка (Evaluator) | ≤ 30s | 1 LLM-вызов с полным контекстом сессии |
| Health check | ≤ 5s | `LITELLM_HEALTH_CHECK_TIMEOUT` |
| Получение списка моделей | ≤ 10s | `LITELLM_MODELS_FETCH_TIMEOUT` |
| Retry backoff | 0.5s–30s per attempt | Exponential: `base * 2^attempt`, capped at `max` |

### 8.2 Cost

| Параметр | Значение |
|---|---|
| LLM-вызовов на ход | 2 (Observer + Interviewer) |
| LLM-вызовов на фидбэк | 1 (Evaluator) |
| LLM-вызовов на сессию (12 ходов) | ~25 (24 ход + 1 фидбэк) |
| Средний расход токенов на ход | ≤ 6 000 (целевое) |
| Суммарный расход на сессию (12 ходов) | ≤ 80 000 токенов (целевое) |
| Стоимость | Для cloud-моделей — пропорциональна объёму токенов. Для локальных моделей — $0.00. Трекается через `x-litellm-response-cost`. |

### 8.3 Reliability

| SLO | Целевое значение | Метод измерения |
|---|---|---|
| Availability | 99% (uptime Gradio + LiteLLM + Redis) | Docker health checks |
| Error rate | ≤ 5% ходов с ошибками | Логи `LLMClientError` |
| Observer parse success rate | ≥ 95% | Отношение успешных парсингов к общему числу вызовов |
| Completion rate | ≥ 70% сессий с фидбэком | `SessionMetrics` |

### 8.4 Scalability

| Параметр | Текущее ограничение | Причина |
|---|---|---|
| Параллельные сессии | 1 на процесс Gradio | `_current_session` — глобальная переменная |
| Персистентность | Файловая система | Нет автоматической ротации логов интервью |
| Cross-session memory | Отсутствует | Каждая сессия независима |
| Multi-user | Не поддерживается | Single-user UI, состояния перезапишутся |

### 8.5 Зависимости от внешних сервисов

| Зависимость | Критичность | Degradation |
|---|---|---|
| **LiteLLM proxy** | Блокирующая | Без proxy невозможна генерация ответов |
| **Redis** | Некритичная для Gradio UI | Используется только FastAPI backend |
| **Langfuse** | Некритичная | Graceful degradation: все вызовы no-op при отключении |
| **PostgreSQL (Langfuse)** | Некритичная | Влияет только на хранение трейсов Langfuse |

---

## 9. Deployment

### 9.1 Контейнеры (Docker Compose)

| Контейнер | Образ | Роль | Порт |
|---|---|---|---|
| `interview-coach` | `Dockerfile.gradio` | Gradio UI | `${GRADIO_PORT:-7860}` |
| `backend` | `Dockerfile` | FastAPI (gunicorn + uvicorn workers) | `${BACKEND_PORT}` (internal) |
| `redis_cache` | `redis:alpine` | Кэш | `${REDIS_CACHE_PORT}` (internal) |
| `nginx` | `nginx:latest` | Reverse proxy | `${NGINX_EXTERNAL_PORT}` |
| `langfuse` | `langfuse/langfuse:2` | Observability UI/API | `${LANGFUSE_PORT:-3000}` |
| `langfuse-db` | `postgres:15-alpine` | Хранение Langfuse | 5432 (internal) |

### 9.2 Конфигурация

Все параметры через `.env` файл, загрузка через `pydantic-settings`. Группы: `AppSettings`, `EnvironmentSettings`, `RedisCacheSettings`, `ClientSideCacheSettings`, `LogSettings`, `LiteLLMSettings`, `InterviewSettings`, `LangfuseSettings`, `GradioUISettings`.

### 9.3 Секреты

| Секрет | Переменная | Где используется |
|---|---|---|
| LiteLLM API key | `LITELLM_API_KEY` | `LLMClient` → Bearer token |
| Langfuse public key | `LANGFUSE_PUBLIC_KEY` | `LangfuseTracker` |
| Langfuse secret key | `LANGFUSE_SECRET_KEY` | `LangfuseTracker` |
| Langfuse DB password | `LANGFUSE_DB_PASSWORD` | `docker-compose.yml` → PostgreSQL |
| NextAuth secret | `LANGFUSE_NEXTAUTH_SECRET` | Langfuse container |
| NextAuth salt | `LANGFUSE_SALT` | Langfuse container |

Все секреты хранятся в `.env`, не коммитятся в репозиторий (`.gitignore`). API key маскируется при логировании: `***{key[-4:]}`.

---

## 10. Стратегия горизонтального масштабирования

### 10.1 Текущее состояние (Single-User)

Текущая архитектура рассчитана на одного пользователя:

- `_current_session` — глобальная переменная в Gradio UI, одна сессия на процесс.
- `InterviewState` — in-memory, не разделяется между инстансами.
- `CircuitBreaker` — singleton, общий для всех `LLMClient` в процессе.
- `SessionMetrics` — хранятся в `LangfuseTracker` по session_id.

### 10.2 Переход к Multi-User

| Этап | Изменения | Сложность |
|---|---|---|
| **Этап 1: Session isolation** | Заменить `_current_session` на `dict[str, InterviewSession]` с маршрутизацией по `session_id` из cookie/token. Gradio поддерживает `gr.State` для per-user state. | Низкая |
| **Этап 2: Аутентификация** | Добавить JWT-аутентификацию. Gradio поддерживает `auth` callback. FastAPI — через `Depends()` middleware. | Средняя |
| **Этап 3: Externalized state** | Перенести `InterviewState` из in-memory в Redis (сериализация через `model_dump_json()` / `model_validate_json()`). Это позволит нескольким инстансам Gradio обслуживать одну сессию. | Средняя |
| **Этап 4: Horizontal scaling** | Запуск нескольких инстансов Gradio за load balancer (nginx upstream). Sticky sessions по `session_id` или shared state через Redis. | Средняя |
| **Этап 5: Rate limiting** | Добавить rate limiting по user_id: X сессий в час, Y сообщений в минуту. Реализация через Redis (sliding window). | Низкая |

### 10.3 Архитектура Multi-User (целевая)

```text
                    ┌─────────────┐
                    │  Nginx LB   │
                    │ (upstream)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴───┐ ┌─────┴─────┐
        │ Gradio #1 │ │ Gr #2 │ │ Gradio #N │
        └─────┬─────┘ └───┬───┘ └─────┬─────┘
              │            │            │
              └────────────┼────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴───┐ ┌─────┴─────┐
        │   Redis   │ │  LLM  │ │ Langfuse  │
        │  (state   │ │ Proxy │ │(observ.)  │
        │  + cache) │ │       │ │           │
        └───────────┘ └───────┘ └───────────┘
```

### 10.4 Оценка нагрузки

| Параметр | Single-user (текущее) | 10 concurrent users | 100 concurrent users |
|---|---|---|---|
| Инстансы Gradio | 1 | 2–3 | 5–10 |
| Redis memory | ~1 MB (cache) | ~50 MB (state + cache) | ~500 MB |
| LLM RPS (пиковый) | 0.2 req/s | 2 req/s | 20 req/s |
| LiteLLM proxy | 1 инстанс | 1 инстанс | 2–3 инстанса |

---

## 11. Кэширование LLM-ответов

### 11.1 Мотивация

Повторные запросы к LLM с идентичными параметрами (модель, промпт, температура, max_tokens) возвращают семантически эквивалентные результаты. Кэширование позволяет:

- Снизить latency повторных запросов с ~5–15s до ~5ms.
- Сократить расходы на токены при повторяющихся сценариях.
- Уменьшить нагрузку на LLM proxy.

### 11.2 Реализация

| Компонент | Описание |
|---|---|
| `LLMResponseCache` | Класс с lazy-подключением к Redis, управляет чтением/записью кэша. |
| Ключ кэша | SHA-256 хеш от `json.dumps({"model", "messages", "temperature", "max_tokens"}, sort_keys=True)`. |
| Хранилище | Redis с TTL. Prefix: `llm_cache:`. |
| TTL | Конфигурируется через `LLM_CACHE_TTL_SECONDS` (default: 3600s). |
| Graceful degradation | При недоступности Redis — кэш пропускается, запрос идёт напрямую к LLM. |

### 11.3 Точка интеграции

Кэширование встроено в `LLMClient.complete()`:

1. Перед LLM-вызовом: вычисляется ключ, проверяется кэш.
2. Cache hit: возвращается кэшированный ответ, LLM-вызов пропускается, генерация в Langfuse помечается `cached=True`.
3. Cache miss: выполняется обычный LLM-вызов, результат сохраняется в кэш.

### 11.4 Конфигурация

| Переменная | Тип | Default | Описание |
|---|---|---|---|
| `LLM_CACHE_ENABLED` | bool | `false` | Включить кэширование LLM-ответов |
| `LLM_CACHE_TTL_SECONDS` | int | `3600` | Время жизни кэша (секунды) |

### 11.5 Ограничения

- Кэшируются только полные ответы (не стриминг).
- При температуре > 0 кэш может возвращать менее разнообразные ответы.
- Изменение системного промпта инвалидирует кэш автоматически (промпт входит в ключ).
- Размер кэша ограничен памятью Redis.