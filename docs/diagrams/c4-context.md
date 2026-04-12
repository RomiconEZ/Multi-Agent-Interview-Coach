# C4 Context Diagram — Multi-Agent Interview Coach

Диаграмма уровня Context показывает систему как «чёрный ящик», пользователей и внешние зависимости.

---

## Диаграмма

```mermaid
flowchart TB
    subgraph USERS["Пользователи"]
        direction LR
        candidate(["👤 Кандидат<br/>Разработчик, проходящий<br/>тренировочное техническое<br/>интервью через веб-интерфейс"])
        operator(["🔧 Оператор<br/>Администратор: deploy,<br/>настройка .env, секреты,<br/>управление логами"])
    end

    subgraph SYSTEM["Multi-Agent Interview Coach"]
        direction LR
        coach["<b>Мультиагентная система</b><br/>технических интервью<br/><br/>• Адаптивная сложность<br/>• Факт-чекинг ответов<br/>• Структурированный фидбэк<br/>• Observability и логирование"]
    end

    subgraph EXTERNAL["Внешние системы (вне Docker Compose)"]
        direction TB
        litellm["<b>LiteLLM Proxy</b><br/><i>OpenAI-compatible API gateway</i><br/>маршрутизация · балансировка ·<br/>retry · cost tracking"]
        llm_backends["<b>LLM Backends</b><br/>Ollama · vLLM (локальные)<br/>DeepSeek · OpenAI (облачные)"]
    end

    %% ── Пользователи → Система ──
    candidate -->|"HTTPS / WebSocket (Gradio :7860)<br/>сообщения · настройки ·<br/>получение вопросов и фидбэка"| coach
    operator -->|"SSH / CLI / Файловая система<br/>Docker Compose · .env ·<br/>просмотр логов"| coach

    %% ── Система → Внешние ──
    coach -->|"HTTP (Bearer token)<br/>POST /v1/chat/completions<br/>GET /v1/models<br/>GET /health/readiness"| litellm
    litellm -->|"HTTP / Provider-specific API<br/>маршрутизация к конкретной<br/>модели"| llm_backends

    %% ── Стили узлов ──
    classDef person fill:#6366f1,stroke:#4338ca,color:#fff,font-weight:bold
    classDef sys fill:#059669,stroke:#047857,color:#fff,font-weight:bold
    classDef ext fill:#d97706,stroke:#b45309,color:#fff

    class candidate,operator person
    class coach sys
    class litellm,llm_backends ext

    %% ── Стили групп ──
    style USERS fill:#1e1b4b,stroke:#6366f1,color:#c7d2fe
    style SYSTEM fill:#022c22,stroke:#059669,color:#a7f3d0
    style EXTERNAL fill:#451a03,stroke:#d97706,color:#fef3c7
```

---

## Как читать диаграмму

| Символ | Значение |
|---|---|
| `───▶` сплошная линия | Взаимодействие с указанием протокола |
| 🟣 фиолетовый | Пользователи (акторы) |
| 🟢 зелёный | Система (чёрный ящик на уровне Context) |
| 🟠 оранжевый | Внешние зависимости (вне Docker Compose) |

---

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

> **Примечание**: Redis, Langfuse Server и PostgreSQL (Langfuse DB) развёрнуты внутри того же Docker Compose стека и не являются внешними зависимостями. Они показаны на уровне C4 Container.

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
| Система → Файловая система | JSON-логи интервью | Локальный | Полная история диалога, данные кандидата |