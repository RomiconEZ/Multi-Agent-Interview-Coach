# C4 Context Diagram — Multi-Agent Interview Coach

Диаграмма уровня Context показывает систему, пользователя и внешние сервисы с границами взаимодействия.

```mermaid
C4Context
    title C4 Context — Multi-Agent Interview Coach

    Person(candidate, "Кандидат", "Разработчик, проходящий тренировочное техническое интервью через веб-интерфейс")
    Person(operator, "Оператор", "Администратор, развёртывающий и настраивающий систему, управляющий секретами и логами")

    System(interview_coach, "Multi-Agent Interview Coach", "Мультиагентная система проведения технических интервью с адаптивной сложностью, факт-чекингом и генерацией структурированного фидбэка")

    System_Ext(litellm_proxy, "LiteLLM Proxy", "OpenAI-compatible API gateway: маршрутизация запросов к LLM-бэкендам (локальные модели, DeepSeek, OpenAI), балансировка, retry, cost tracking")
    System_Ext(llm_backend, "LLM Backend(s)", "Один или несколько LLM-провайдеров: локальные модели (Ollama, vLLM), облачные (DeepSeek API, OpenAI API)")
    System_Ext(langfuse, "Langfuse (self-hosted)", "Платформа observability: хранение трейсов интервью, генераций LLM, метрик токенов, score'ов сессий")
    System_Ext(langfuse_db, "PostgreSQL (Langfuse)", "Реляционная БД для хранения данных Langfuse")
    System_Ext(redis, "Redis", "In-memory хранилище для кэширования на уровне FastAPI backend")

    Rel(candidate, interview_coach, "Отправляет сообщения, получает вопросы и фидбэк", "HTTPS / WebSocket (Gradio)")
    Rel(operator, interview_coach, "Настраивает .env, управляет Docker Compose, просматривает логи", "SSH / CLI / Файловая система")

    Rel(interview_coach, litellm_proxy, "Отправляет chat completion запросы, получает ответы LLM", "HTTP POST /v1/chat/completions, GET /v1/models, GET /health/readiness")
    Rel(litellm_proxy, llm_backend, "Маршрутизирует запросы к конкретным моделям", "HTTP / Provider-specific API")

    Rel(interview_coach, langfuse, "Отправляет трейсы, генерации, span'ы и score'ы", "HTTP (Langfuse SDK, async batch)")
    Rel(langfuse, langfuse_db, "Хранит данные трейсов и метрик", "TCP / PostgreSQL wire protocol")

    Rel(interview_coach, redis, "Кэширование ответов FastAPI backend", "TCP / Redis protocol")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```

## Описание границ

### Пользователи

| Актор | Взаимодействие с системой |
|---|---|
| **Кандидат** | Взаимодействует через Gradio веб-интерфейс: начинает интервью, отвечает на вопросы, получает фидбэк. Не имеет прямого доступа к внутренним сервисам. |
| **Оператор** | Развёртывает систему через Docker Compose, настраивает `.env`, управляет секретами (API ключи LiteLLM, Langfuse), просматривает логи приложения и интервью, настраивает ротацию и очистку данных. |

### Внешние системы

| Система | Протокол | Критичность | Graceful degradation |
|---|---|---|---|
| **LiteLLM Proxy** | HTTP (OpenAI-compatible) | Блокирующая — без proxy невозможна генерация ответов | Circuit breaker (OPEN после 5 сбоев, recovery 60s), retry с exponential backoff, health check перед стартом сессии |
| **LLM Backend(s)** | HTTP / Provider API | Блокирующая (транзитно через LiteLLM) | Fallback между моделями на уровне LiteLLM proxy (`config.yaml`), `allowed_fails` + `cooldown_time` |
| **Langfuse** | HTTP (SDK) | Некритичная | При `LANGFUSE_ENABLED=false` или отсутствии ключей — все вызовы no-op. Бизнес-логика не затрагивается. |
| **PostgreSQL (Langfuse)** | TCP | Некритичная | Влияет только на хранение данных Langfuse |
| **Redis** | TCP | Некритичная для Gradio UI | Используется только FastAPI backend для кэширования. Gradio UI работает без Redis. |

### Границы доверия

```text
┌──────────────────────────────────────────────────────────────────┐
│                    Trust Boundary: Operator Infrastructure       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              Docker Compose Network (internal)             │  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────┐  ┌──────────────────────┐ │  │
│  │  │ Gradio UI    │  │ FastAPI  │  │ Redis                │ │  │
│  │  │ (interview-  │  │ Backend  │  │ (redis_cache)        │ │  │
│  │  │  coach)      │  │          │  │                      │ │  │
│  │  └──────┬───────┘  └────┬─────┘  └──────────────────────┘ │  │
│  │         │               │                                  │  │
│  │  ┌──────┴───────────────┴──────────────────────────────┐   │  │
│  │  │              LiteLLM Proxy                          │   │  │
│  │  │  (отдельный Docker Compose или внешний сервис)      │   │  │
│  │  └─────────────────────┬───────────────────────────────┘   │  │
│  │                        │                                   │  │
│  │  ┌─────────────┐  ┌───┴────────┐                          │  │
│  │  │ Langfuse    │  │ Langfuse   │                          │  │
│  │  │ (UI/API)    │  │ DB (PG)    │                          │  │
│  │  └─────────────┘  └────────────┘                          │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                        │
                        ▼ (при использовании cloud-моделей)
┌──────────────────────────────────────────────────────────────────┐
│               Trust Boundary: External LLM Providers             │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ DeepSeek API │  │ OpenAI API   │  │ Другие провайдеры    │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│                                                                  │
│  ⚠️ Текст сообщений кандидата передаётся провайдеру              │
│     в соответствии с его условиями обработки данных               │
└──────────────────────────────────────────────────────────────────┘
```

### Потоки данных через границы

| Поток | Данные | Направление | Конфиденциальность |
|---|---|---|---|
| Кандидат → Система | Текст сообщений, имя, позиция, опыт, технологии | Входящий | Персональные данные, обрабатываются локально при self-hosted deployment |
| Система → Кандидат | Вопросы интервью, фидбэк, метрики | Исходящий | Генерированный контент |
| Система → LiteLLM | Messages (system prompt + history + user input), параметры модели | Исходящий | Содержит текст сообщений кандидата в составе промпта |
| LiteLLM → LLM Backend | Проксированные запросы | Исходящий (транзитно) | При cloud-моделях — данные покидают периметр инфраструктуры |
| Система → Langfuse | Трейсы, генерации, span'ы, score'ы, имя кандидата (user_id) | Исходящий | Метаданные сессии, может содержать PII |
| Система → Файловая система | JSON-логи интервью | Локальный | Полная история диалога, данные кандидата |