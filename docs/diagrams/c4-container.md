# C4 Container Diagram — Multi-Agent Interview Coach

Диаграмма уровня контейнеров: показывает runtime-компоненты системы, их технологии и взаимодействия.

---

## Диаграмма

```mermaid
flowchart TB
    user(["👤 Кандидат<br/>Разработчик, проходящий<br/>тренировочное интервью"])

    subgraph SYSTEM["Multi-Agent Interview Coach — Docker Compose (network: internal)"]
        direction TB

        subgraph ENTRY["Точки входа"]
            direction LR
            gradio["<b>Gradio UI</b><br/><i>Python, Gradio 5.x</i><br/>Чат · настройки агентов ·<br/>фидбэк · логи"]
            subgraph API_GW["API Gateway"]
                direction TB
                nginx["<b>Nginx</b><br/><i>nginx:latest</i><br/>Reverse proxy · :80<br/>блокировка /docs извне"]
                fastapi["<b>FastAPI Backend</b><br/><i>Gunicorn + Uvicorn</i><br/>REST API · middleware ·<br/>Cache-Control"]
            end
        end

        subgraph CORE["Ядро системы"]
            direction LR
            session["<b>InterviewSession</b><br/><i>Оркестратор</i><br/>lifecycle · 6 стадий ·<br/>адаптация сложности"]
            state[("<b>InterviewState</b><br/><i>In-Memory, Pydantic</i><br/>candidate · turns ·<br/>difficulty · skills · gaps")]
        end

        subgraph AGENTS["Агенты"]
            direction LR
            observer["<b>ObserverAgent</b><br/>Анализ ответа ·<br/>факт-чекинг ·<br/>JSON + retry ×2"]
            interviewer["<b>InterviewerAgent</b><br/>Генерация реплик ·<br/>обработка сценариев ·<br/>текстовый вывод"]
            evaluator["<b>EvaluatorAgent</b><br/>Вердикт · tech review ·<br/>soft skills · роадмап ·<br/>JSON + retry ×2"]
        end

        subgraph LLM_INFRA["LLM-инфраструктура"]
            direction LR
            llm_client["<b>LLMClient</b><br/><i>httpx, async</i><br/>retry · exp. backoff ·<br/>health check · cost tracking"]
            circuit_breaker["<b>CircuitBreaker</b><br/>CLOSED → OPEN → HALF_OPEN<br/>threshold: 5 · recovery: 60s"]
        end

        subgraph OBS["Observability и логирование"]
            direction LR
            langfuse_tracker["<b>LangfuseTracker</b><br/><i>Langfuse SDK, Singleton</i><br/>traces · generations ·<br/>spans · scores · metrics"]
            interview_logger["<b>InterviewLogger</b><br/>interview_log_*.json<br/>interview_detailed_*.json"]
        end

        subgraph INFRA["Инфраструктурные сервисы (Docker)"]
            direction LR
            redis[("<b>Redis</b><br/><i>redis:alpine</i><br/>LLM response cache ·<br/>FastAPI app cache")]
            langfuse_srv["<b>Langfuse Server</b><br/><i>langfuse/langfuse:2</i><br/>Observability UI ·<br/>трейсы · метрики"]
            langfuse_db[("<b>PostgreSQL</b><br/><i>postgres:15-alpine</i><br/>Langfuse data store")]
        end

        subgraph STORES["Хранилища (Filesystem)"]
            direction LR
            logs_json[("📁 Interview Logs<br/>JSON files<br/>основной + детальный")]
            app_logs[("📁 Application Logs<br/>system.log · personal.log<br/>RotatingFile 10MB × 2")]
        end
    end

    subgraph EXTERNAL["Внешние системы (вне Docker Compose)"]
        direction LR
        litellm["<b>LiteLLM Proxy</b><br/><i>OpenAI-compatible API</i><br/>маршрутизация к LLM-бэкендам"]
        llm_backends["<b>LLM Backends</b><br/>Ollama · DeepSeek ·<br/>OpenAI · другие"]
    end

    %% ── Пользователь → Точки входа ──
    user -->|"HTTPS / WebSocket<br/>:7860 · чат, настройки"| gradio
    user -->|"HTTP :80<br/>REST API"| nginx

    %% ── API Gateway ──
    nginx -->|"HTTP proxy<br/>→ backend:8000"| fastapi

    %% ── UI → Ядро ──
    gradio -->|"start · process_message<br/>generate_feedback · close"| session

    %% ── Ядро ↔ Состояние ──
    session <-->|"read · mutate"| state

    %% ── Ядро → Агенты ──
    session -->|"Stage 1: process()"| observer
    session -->|"Stage 5: process()"| interviewer
    session -->|"generate_feedback()"| evaluator

    %% ── Агенты → LLM ──
    observer -->|"complete(json_mode)"| llm_client
    interviewer -->|"complete(text)"| llm_client
    evaluator -->|"complete(json_mode)"| llm_client

    %% ── LLM-инфраструктура ──
    llm_client -->|"check · record"| circuit_breaker

    %% ── LLM → Внешний API ──
    llm_client -->|"POST /v1/chat/completions<br/>GET /v1/models · /health"| litellm
    litellm -->|"Provider-specific API"| llm_backends

    %% ── LLM кэширование ──
    llm_client -.->|"LLM response cache<br/>(RedisLLMCache)"| redis

    %% ── Observability (пунктир — некритичные связи) ──
    session -.->|"spans · scores"| langfuse_tracker
    llm_client -.->|"create/end generation<br/>usage · cost"| langfuse_tracker
    session -.->|"save_session<br/>save_raw_log"| interview_logger
    session -.->|"system.log"| app_logs

    %% ── Запись в хранилища ──
    interview_logger -.->|"write JSON"| logs_json
    langfuse_tracker -.->|"HTTP (SDK, async)"| langfuse_srv
    langfuse_srv -->|"TCP :5432"| langfuse_db

    %% ── FastAPI → инфраструктура ──
    fastapi -->|"TCP :6379<br/>app cache"| redis
    fastapi -.->|"lifecycle shutdown"| langfuse_srv

    %% ── Стили узлов ──
    classDef person fill:#6366f1,stroke:#4338ca,color:#fff,font-weight:bold
    classDef ui fill:#0ea5e9,stroke:#0369a1,color:#fff
    classDef core fill:#3b82f6,stroke:#1d4ed8,color:#fff
    classDef agent fill:#8b5cf6,stroke:#6d28d9,color:#fff
    classDef llm fill:#f59e0b,stroke:#d97706,color:#fff
    classDef obs fill:#10b981,stroke:#047857,color:#fff
    classDef store fill:#6b7280,stroke:#374151,color:#fff
    classDef infra fill:#64748b,stroke:#334155,color:#fff
    classDef ext fill:#94a3b8,stroke:#475569,color:#1e293b

    class user person
    class gradio,fastapi ui
    class nginx infra
    class session,state core
    class observer,interviewer,evaluator agent
    class llm_client,circuit_breaker llm
    class langfuse_tracker,interview_logger obs
    class logs_json,app_logs store
    class redis,langfuse_srv,langfuse_db infra
    class litellm,llm_backends ext

    %% ── Стили групп ──
    style SYSTEM fill:#0f172a,stroke:#334155,color:#e2e8f0
    style ENTRY fill:#082f49,stroke:#0ea5e9,color:#bae6fd
    style API_GW fill:#0c4a6e,stroke:#0ea5e9,color:#bae6fd
    style CORE fill:#172554,stroke:#3b82f6,color:#bfdbfe
    style AGENTS fill:#2e1065,stroke:#8b5cf6,color:#ddd6fe
    style LLM_INFRA fill:#451a03,stroke:#f59e0b,color:#fef3c7
    style OBS fill:#052e16,stroke:#10b981,color:#a7f3d0
    style INFRA fill:#1e293b,stroke:#64748b,color:#cbd5e1
    style STORES fill:#1f2937,stroke:#6b7280,color:#d1d5db
    style EXTERNAL fill:#1c1917,stroke:#78716c,color:#d6d3d1
```

---

## Как читать диаграмму

| Символ | Значение |
|---|---|
| `───▶` сплошная линия | Основной поток данных (критичный путь) |
| `- - ▶` пунктирная линия | Некритичный поток (observability, логирование, кэш) |
| `◀──▶` двунаправленная | Чтение и запись (InterviewSession ↔ InterviewState) |
| `(( ))` цилиндр | Хранилище данных (Redis, PostgreSQL, Filesystem) |
| Цветовые группы | 🔵 UI · 🔷 Ядро · 🟣 Агенты · 🟡 LLM · 🟢 Observability · ⚫ Инфраструктура · ⚪ Внешние |

---

## Пояснения

### Граница системы

Все компоненты внутри `SYSTEM` развёрнуты единым `docker-compose up` в общей bridge-сети `internal`. Взаимодействие Python-компонентов (Gradio UI, InterviewSession, Agents, LLMClient) — in-process вызовы внутри одного контейнера `interview-coach`. FastAPI Backend работает в отдельном контейнере `backend`.

### Инфраструктурные сервисы (внутри Docker Compose)

| Сервис | Docker-образ | Порт | Назначение |
|---|---|---|---|
| **Nginx** | `nginx:latest` | :80 (внешний) → backend:8000 | Reverse proxy для FastAPI, блокировка /docs извне |
| **Redis** | `redis:alpine` | :6379 (internal) | LLM response cache (`RedisLLMCache`) + FastAPI app cache |
| **Langfuse Server** | `langfuse/langfuse:2` | :3000 (внешний) | Observability UI, приём трейсов/генераций/span'ов |
| **PostgreSQL** | `postgres:15-alpine` | :5432 (internal) | Хранение данных Langfuse |

### Внешние системы (вне Docker Compose)

| Система | Протокол | Критичность |
|---|---|---|
| **LiteLLM Proxy** | HTTP, OpenAI-compatible | Блокирующая — без proxy невозможна генерация ответов. Circuit breaker (OPEN после 5 сбоев, recovery 60s). |
| **LLM Backends** | HTTP / Provider API | Блокирующая (транзитно через LiteLLM). Ollama, DeepSeek, OpenAI и другие. |

### Потоки данных

1. **Горячий путь (ход интервью)**: User → Gradio UI → InterviewSession → Observer → LLMClient → (Redis cache check) → LiteLLM Proxy → LLM Backend → обратно → (Redis cache write) → Interviewer → LLMClient → LiteLLM → обратно → InterviewSession → Gradio UI → User.
2. **REST API путь**: User → Nginx (:80) → FastAPI Backend → Redis (app cache).
3. **Финализация**: InterviewSession → Evaluator → LLMClient → LiteLLM → обратно → InterviewLogger → Filesystem.
4. **Observability**: LLMClient → LangfuseTracker → Langfuse Server → PostgreSQL (async flush). FastAPI lifespan управляет shutdown.
5. **LLM кэширование**: LLMClient → RedisLLMCache → Redis. При попадании в кэш — LiteLLM не вызывается (cost=0).

### Хранилища

| Хранилище | Тип | Данные | Lifecycle |
|---|---|---|---|
| InterviewState | In-memory (Pydantic) | Состояние сессии | Создаётся при start(), теряется при crash |
| Interview Logs | Filesystem (JSON) | interview_log_*.json, interview_detailed_*.json | Персистентны, без автоматической ротации |
| Application Logs | Filesystem (text) | system.log, personal.log | RotatingFileHandler, 10 MB × 2 backup |
| PostgreSQL | Docker volume | Трейсы, генерации, метрики Langfuse | Персистентны, управляется Langfuse |
| Redis | In-memory | LLM response cache (TTL-based) + FastAPI app cache | Volatile |