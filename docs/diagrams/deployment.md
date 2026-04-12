# Deployment Diagram — Сетевая топология

Диаграмма описывает физическое размещение компонентов системы в Docker Compose.

---

## 1. Сетевая топология

```mermaid
flowchart TB
    subgraph EXTERNAL["🌐 Внешний доступ"]
        Browser["Браузер пользователя"]
        LiteLLMProxy["LiteLLM Proxy<br/>(OpenAI-compatible API)"]
        LLMBackend["LLM Backend<br/>(Ollama / DeepSeek API /<br/>другой провайдер)"]
    end

    subgraph DOCKER["Docker Compose Network: internal (bridge)"]

        subgraph GRADIO_CONTAINER["📦 interview-coach<br/>(Dockerfile.gradio)"]
            GradioApp["Gradio UI<br/>Python + Gradio 5.x<br/>InterviewSession<br/>Agents (Observer, Interviewer, Evaluator)<br/>LLMClient, LangfuseTracker"]
        end

        subgraph BACKEND_CONTAINER["📦 backend<br/>(Dockerfile)"]
            FastAPI["FastAPI Backend<br/>Gunicorn + Uvicorn workers<br/>REST API, Middleware<br/>Redis client"]
        end

        subgraph NGINX_CONTAINER["📦 nginx<br/>(nginx:latest)"]
            Nginx["Nginx<br/>Reverse Proxy<br/>→ backend:8000"]
        end

        subgraph REDIS_CONTAINER["📦 redis_cache<br/>(redis:alpine)"]
            Redis["Redis<br/>In-memory cache"]
        end

        subgraph LANGFUSE_CONTAINER["📦 langfuse<br/>(langfuse/langfuse:2)"]
            LangfuseServer["Langfuse Server<br/>Observability UI<br/>Traces, Generations,<br/>Spans, Scores"]
        end

        subgraph LANGFUSE_DB_CONTAINER["📦 langfuse-db<br/>(postgres:15-alpine)"]
            Postgres["PostgreSQL 15<br/>Langfuse data store"]
        end

    end

    %% Внешний доступ
    Browser -->|"HTTP :7860<br/>(GRADIO_PORT)"| GradioApp
    Browser -->|"HTTP :80<br/>(NGINX_EXTERNAL_PORT)"| Nginx
    Browser -->|"HTTP :3000<br/>(LANGFUSE_PORT)"| LangfuseServer

    %% Внутренние связи
    Nginx -->|"HTTP → backend:8000<br/>(BACKEND_PORT, internal)"| FastAPI
    FastAPI -->|"TCP :6379<br/>(REDIS_CACHE_PORT, internal)"| Redis
    FastAPI -.->|"HTTP (Langfuse SDK)"| LangfuseServer
    GradioApp -.->|"HTTP (Langfuse SDK)"| LangfuseServer
    GradioApp -->|"HTTP<br/>POST /v1/chat/completions<br/>GET /v1/models<br/>GET /health/readiness"| LiteLLMProxy
    LiteLLMProxy -->|"HTTP<br/>Provider-specific API"| LLMBackend
    LangfuseServer -->|"TCP :5432<br/>(internal)"| Postgres

    %% Стили
    style EXTERNAL fill:#1a2744,stroke:#6366f1,color:#e2e8f0
    style DOCKER fill:#0d1117,stroke:#30363d,color:#e2e8f0
    style GRADIO_CONTAINER fill:#1a3d2e,stroke:#10b981,color:#e2e8f0
    style BACKEND_CONTAINER fill:#1a3a5c,stroke:#4a9eff,color:#e2e8f0
    style NGINX_CONTAINER fill:#3d2e1a,stroke:#f59e0b,color:#e2e8f0
    style REDIS_CONTAINER fill:#3d1a1a,stroke:#ef4444,color:#e2e8f0
    style LANGFUSE_CONTAINER fill:#2d1a4e,stroke:#8b5cf6,color:#e2e8f0
    style LANGFUSE_DB_CONTAINER fill:#2d1a4e,stroke:#8b5cf6,color:#e2e8f0
```

---

## 2. Порты и доступность

| Контейнер | Образ | Внутренний порт | Внешний порт | Протокол | Доступ извне |
|---|---|---|---|---|---|
| `interview-coach` | `Dockerfile.gradio` | 7860 | `${GRADIO_PORT:-7860}` | HTTP / WebSocket | ✅ Да — основной UI |
| `backend` | `Dockerfile` | `${BACKEND_PORT}` (8000) | — (`expose` only) | HTTP | ❌ Нет — только через Nginx |
| `redis_cache` | `redis:alpine` | `${REDIS_CACHE_PORT}` (6379) | — (`expose` only) | TCP (Redis protocol) | ❌ Нет — только внутри сети |
| `nginx` | `nginx:latest` | 80 | `${NGINX_EXTERNAL_PORT}` | HTTP | ✅ Да — API gateway |
| `langfuse` | `langfuse/langfuse:2` | 3000 | `${LANGFUSE_PORT:-3000}` | HTTP | ✅ Да — observability UI |
| `langfuse-db` | `postgres:15-alpine` | 5432 | — (no expose) | TCP (PostgreSQL) | ❌ Нет — только для langfuse |

### Маршрутизация запросов

```mermaid
flowchart LR
    subgraph USER["Пользователь"]
        B["Браузер"]
    end

    subgraph PORTS["Открытые порты"]
        P7860[":7860"]
        P80[":80"]
        P3000[":3000"]
    end

    subgraph TARGETS["Целевые контейнеры"]
        G["interview-coach<br/>(Gradio UI)"]
        N["nginx → backend<br/>(FastAPI REST API)"]
        L["langfuse<br/>(Observability UI)"]
    end

    B --> P7860 --> G
    B --> P80 --> N
    B --> P3000 --> L

    style USER fill:#1a2744,stroke:#6366f1,color:#e2e8f0
    style PORTS fill:#3d2e1a,stroke:#f59e0b,color:#e2e8f0
    style TARGETS fill:#1a3d2e,stroke:#10b981,color:#e2e8f0
```

---

## 3. Volumes

| Volume | Тип | Контейнер | Mount point | Назначение |
|---|---|---|---|---|
| `redis-cache-data` | Docker named volume | `redis_cache` | `/data` | Персистентность кэша Redis (RDB/AOF snapshots) |
| `interview-logs` | Docker named volume | `interview-coach` | `/code/interview_logs` | Логи интервью: `interview_log_*.json`, `interview_detailed_*.json` |
| `langfuse-db-data` | Docker named volume | `langfuse-db` | `/var/lib/postgresql/data` | Данные PostgreSQL (трейсы, генерации, span'ы, score'ы Langfuse) |
| `./src/app` (bind) | Bind mount | `interview-coach`, `backend` | `/code/app` | Исходный код (dev-режим — hot reload) |
| `.env` (env_file) | Docker env_file | `interview-coach`, `backend` | — (переменные окружения) | Конфигурация окружения: значения из файла передаются как ENV-переменные контейнера |
| `./default.conf` (bind) | Bind mount | `nginx` | `/etc/nginx/conf.d/default.conf` | Конфигурация Nginx reverse proxy |

### Схема volume mounts

```mermaid
flowchart LR
    subgraph HOST["Хост-система (файловая система)"]
        SRC["./src/app<br/>(исходный код)"]
        NGCONF["./default.conf<br/>(nginx config)"]
    end

    subgraph NAMED_VOLUMES["Docker Named Volumes"]
        V_REDIS["redis-cache-data"]
        V_LOGS["interview-logs"]
        V_PG["langfuse-db-data"]
    end

    subgraph CONTAINERS["Контейнеры"]
        C_GRADIO["interview-coach"]
        C_BACKEND["backend"]
        C_NGINX["nginx"]
        C_REDIS["redis_cache"]
        C_PGDB["langfuse-db"]
    end

    SRC -->|bind| C_GRADIO
    SRC -->|bind| C_BACKEND
    NGCONF -->|bind| C_NGINX

    V_LOGS -->|named| C_GRADIO
    V_REDIS -->|named| C_REDIS
    V_PG -->|named| C_PGDB

    style HOST fill:#1a3a5c,stroke:#4a9eff,color:#e2e8f0
    style NAMED_VOLUMES fill:#2d1a4e,stroke:#8b5cf6,color:#e2e8f0
    style CONTAINERS fill:#1a3d2e,stroke:#10b981,color:#e2e8f0
```

---

## 4. Сетевые зависимости при запуске

### 4.1 Граф зависимостей

```mermaid
flowchart BT
    langfuse_db["langfuse-db<br/>(postgres:15-alpine)<br/>healthcheck: pg_isready"]
    langfuse["langfuse<br/>(langfuse/langfuse:2)"]
    redis["redis_cache<br/>(redis:alpine)"]
    backend["backend<br/>(FastAPI)"]
    nginx["nginx<br/>(nginx:latest)"]
    gradio["interview-coach<br/>(Gradio UI)"]

    langfuse_db -->|"condition:<br/>service_healthy"| langfuse
    langfuse -->|"condition:<br/>service_started"| gradio
    redis -->|"condition:<br/>service_started"| gradio
    redis -->|"depends_on"| backend
    langfuse -->|"depends_on"| backend
    backend -->|"depends_on"| nginx

    style langfuse_db fill:#2d1a4e,stroke:#8b5cf6,color:#e2e8f0
    style langfuse fill:#2d1a4e,stroke:#8b5cf6,color:#e2e8f0
    style redis fill:#3d1a1a,stroke:#ef4444,color:#e2e8f0
    style backend fill:#1a3a5c,stroke:#4a9eff,color:#e2e8f0
    style nginx fill:#3d2e1a,stroke:#f59e0b,color:#e2e8f0
    style gradio fill:#1a3d2e,stroke:#10b981,color:#e2e8f0
```

### 4.2 Порядок запуска

| Очередь | Контейнер | Условие старта | Зависит от |
|---|---|---|---|
| 1 | `langfuse-db` | Немедленно | — |
| 1 | `redis_cache` | Немедленно | — |
| 2 | `langfuse` | `langfuse-db` healthy (`pg_isready` — interval: 5s, timeout: 5s, retries: 5) | `langfuse-db` |
| 3 | `backend` | `redis_cache` started, `langfuse` started | `redis_cache`, `langfuse` |
| 3 | `interview-coach` | `redis_cache` started, `langfuse` started | `redis_cache`, `langfuse` |
| 4 | `nginx` | `backend` started | `backend` |

### 4.3 Health checks

| Контейнер | Тип проверки | Команда | Параметры |
|---|---|---|---|
| `langfuse-db` | Docker healthcheck | `pg_isready -U ${LANGFUSE_DB_USER:-langfuse}` | interval: 5s, timeout: 5s, retries: 5 |
| `interview-coach` | Application-level | `LLMClient.check_health()` → `GET /health/readiness` (LiteLLM) | Вызывается при `InterviewSession.start()`, timeout: 5s |

### 4.4 Restart policy

Все контейнеры используют единую политику перезапуска:

```
restart: on-failure:3
```

| Параметр | Значение | Описание |
|---|---|---|
| Политика | `on-failure` | Перезапуск только при ненулевом exit code |
| Максимум попыток | 3 | После 3 неудачных перезапусков контейнер остаётся остановленным |

---

## 5. Сетевая конфигурация

### 5.1 Docker Network

| Параметр | Значение |
|---|---|
| Имя сети | `internal` |
| Driver | `bridge` |
| Scope | Все 6 контейнеров |
| DNS | Встроенный Docker DNS (контейнеры обращаются друг к другу по имени сервиса) |

### 5.2 Внутренние DNS-имена

Контейнеры взаимодействуют по именам сервисов Docker Compose (встроенный DNS resolver):

| Клиент | Целевой сервис | DNS-имя | Порт | Пример URL |
|---|---|---|---|---|
| `interview-coach` | LiteLLM Proxy | (внешний, настраивается через `LITELLM_BASE_URL`) | 4000 | `http://host.docker.internal:4000` |
| `interview-coach` | Langfuse | `langfuse` | 3000 | `http://langfuse:3000` |
| `backend` | Redis | `redis_cache` | 6379 | `redis://redis_cache:6379` |
| `backend` | Langfuse | `langfuse` | 3000 | `http://langfuse:3000` |
| `nginx` | Backend | `backend` | 8000 | `http://backend:8000` |
| `langfuse` | PostgreSQL | `langfuse-db` | 5432 | `postgresql://langfuse:***@langfuse-db:5432/langfuse` |

### 5.3 Nginx конфигурация

Файл: `default.conf`

| Параметр | Значение |
|---|---|
| `listen` | 80 |
| `proxy_pass` | `http://backend:8000` |
| `client_max_body_size` | 3000M |
| `client_body_timeout` | 600s |
| `proxy_connect_timeout` | 600s |
| `proxy_send_timeout` | 600s |
| `proxy_read_timeout` | 600s |

Заголовки: `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto` — проксируются к backend.

---

## 6. Внешние зависимости (вне Docker Compose)

```mermaid
flowchart LR
    subgraph DOCKER["Docker Compose: internal"]
        GRADIO["interview-coach"]
    end

    subgraph EXTERNAL["Внешние сервисы"]
        OLLAMA["Ollama<br/>(host.docker.internal:11434)<br/>Локальная LLM"]
        LITELLM_PROXY["LiteLLM Proxy<br/>(может быть внешним<br/>или локальным)"]
        DEEPSEEK["DeepSeek API<br/>(api.deepseek.com)<br/>Облачная LLM"]
    end

    GRADIO -->|"LITELLM_BASE_URL"| LITELLM_PROXY
    LITELLM_PROXY -->|"ollama/model-name"| OLLAMA
    LITELLM_PROXY -->|"deepseek/deepseek-chat"| DEEPSEEK

    style DOCKER fill:#1a3d2e,stroke:#10b981,color:#e2e8f0
    style EXTERNAL fill:#3d2e1a,stroke:#f59e0b,color:#e2e8f0
```

> **Примечание**: LiteLLM Proxy может быть запущен как отдельный контейнер вне этого Docker Compose (с собственной конфигурацией в `llm-gateway-litellm/config.yaml`) или использоваться как внешний сервис. Адрес задаётся через переменную `LITELLM_BASE_URL`.

---

## 7. Переменные окружения для сетевой конфигурации

| Переменная | Default | Описание |
|---|---|---|
| `GRADIO_PORT` | `7860` | Внешний порт Gradio UI |
| `BACKEND_PORT` | `8000` | Внутренний порт FastAPI backend |
| `NGINX_EXTERNAL_PORT` | — | Внешний порт Nginx (API gateway) |
| `REDIS_CACHE_HOST` | `localhost` | Хост Redis (в Docker: `redis_cache`) |
| `REDIS_CACHE_PORT` | `6379` | Порт Redis |
| `LANGFUSE_PORT` | `3000` | Внешний порт Langfuse UI |
| `LANGFUSE_HOST` | `http://localhost:3000` | URL Langfuse (в Docker: `http://langfuse:3000`) |
| `LITELLM_BASE_URL` | `http://localhost:4000` | URL LiteLLM Proxy |
| `LANGFUSE_DB_USER` | `langfuse` | Пользователь PostgreSQL (Langfuse) |
| `LANGFUSE_DB_PASSWORD` | `langfuse` | Пароль PostgreSQL (Langfuse) |
| `LANGFUSE_DB_NAME` | `langfuse` | Имя базы данных PostgreSQL (Langfuse) |
| `COMPOSE_PROJECT_NAME` | — | Префикс имён контейнеров |