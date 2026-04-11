# Multi-Agent Interview Coach

Система технического интервью с мультиагентной логикой (Observer / Interviewer / Evaluator), FastAPI backend и
веб-интерфейсом на Gradio. Интеграция с LLM выполняется через LiteLLM proxy (OpenAI-compatible API). Для кэширования
используется Redis.

Дополнительно в проект включён **локальный Langfuse (self-hosted)** для observability: трекинг вызовов LLM,
трейсов интервью, метрик токенов и статистики сессии.

Junior- и Middle-разработчики часто тратят значительные суммы на менторов и карьерных консультантов для подготовки к техническим интервью, либо готовятся самостоятельно без структурированной обратной связи. Отсутствие объективной оценки сильных и слабых сторон приводит к повторяющимся ошибкам и неэффективной подготовке. Multi-Agent Interview Coach решает эту проблему, предоставляя бесплатную AI-систему, которая проводит реалистичное техническое интервью с адаптивной сложностью и детальным фидбэком.

---

## Возможности

- Проведение технического интервью в чат-формате.
- Мультиагентный пайплайн:
    - анализ ответа кандидата (в т. ч. детекция галлюцинаций / off-topic / встречных вопросов / бессмыслицы),
    - генерация следующего вопроса с адаптацией сложности,
    - формирование финального структурированного фидбэка.
- Адаптивная сложность вопросов (BASIC → INTERMEDIATE → ADVANCED → EXPERT).
- Поддержка описания вакансии для персонализации интервью.
- Сохранение логов интервью:
    - основной лог по формату ТЗ,
    - детальный лог с внутренними мыслями агентов,
    - метрики токенов сессии (в детальном логе и в финальном фидбэке в UI).
- Observability через **Langfuse (локально)**:
    - трейсы интервью (greeting / user_message / observer_analysis / interviewer_response / final_feedback),
    - статистика токенов по сессии и по агентам,
    - диагностика LLM ошибок (generation end with error).
- Запуск через Docker Compose (Gradio + FastAPI backend + Redis + Nginx + Langfuse + PostgreSQL).
- Централизованная конфигурация через `.env` (pydantic-settings).
- Ротация логов приложения (system.log / personal.log).

---

## Дополнительные возможности стабильности диалога и качества оценки

- **Автоматическое извлечение данных о кандидате из текста.**
  Система извлекает из сообщений кандидата атрибуты профиля (имя, позиция, заявленный грейд, опыт, технологии) и
  сохраняет их в состоянии интервью для дальнейшей персонализации вопросов и логирования.

- **Уточнение недостающих данных.**
  Если критичная информация отсутствует (например, позиция/стек), интервью начинается с этапа представления и
  продолжает корректно собирать контекст, избегая нерелевантных вопросов.

- **Завершение интервью по распознаванию намерения пользователя.**
  Система распознаёт команды/намерение завершить интервью (например: «стоп», «давай фидбэк») и корректно переводит
  сессию в финализацию с генерацией итогового фидбэка и сохранением логов.

- **Сохранение «активного технического вопроса» при попытках смены темы.**
  При уходе от темы или попытках сменить технический вопрос система сохраняет якорь последнего активного вопроса и
  возвращает диалог к нему до получения ответа либо явного «не знаю».

- **Устойчивость к галлюцинациям за счёт проверки фактов.**
  При выявлении фактически неверных утверждений система маркирует их как ошибку, корректно сообщает правильную
  информацию и фиксирует пробелы в знаниях, не подменяя ответ кандидата.

- **Детекция бессмысленных сообщений.**
  Система распознаёт случайный набор символов, тесты клавиатуры и спам, и корректно запрашивает повторный ввод,
  переформулируя текущий вопрос.

- **Атомарность мутаций состояния.**
  Неидемпотентные изменения состояния применяются только при полном успехе всех агентов. При сбое Interviewer
  корректировка сложности откатывается к предыдущему значению.

---

## Архитектура

### Основные компоненты

- **UI** (`src/app/ui/gradio_app.py`, `src/app/ui/styles.py`): веб-интерфейс и управление сессией.
- **InterviewSession** (`src/app/interview/session.py`): оркестрация агентов, состояние интервью, лимиты ходов,
  генерация фидбэка, сбор метрик Langfuse.
- **Агенты** (`src/app/agents/*`): `ObserverAgent`, `InterviewerAgent`, `EvaluatorAgent`.
- **LLMClient** (`src/app/llm/client.py`): HTTP-клиент к LiteLLM proxy + трекинг generation в Langfuse.
- **Парсер ответов** (`src/app/llm/response_parser.py`): извлечение JSON и reasoning из текстовых ответов LLM.
- **Утилита моделей** (`src/app/llm/models.py`): получение списка доступных моделей из LiteLLM API.
- **LangfuseTracker** (`src/app/observability/langfuse_client.py`): трекинг трейсов/генераций и сбор метрик токенов.
- **FastAPI backend** (`src/app/main.py`, `src/app/core/setup.py`): приложение, middleware, документация.
- **Redis cache** (`src/app/utils/cache.py`): хранение connection pool и клиента.
- **Логирование** (`src/app/core/logger_setup.py`): форматтер с TZ, фильтры для system/personal логов, ротация.

### Поток обработки сообщения (высокоуровнево)

1. Пользователь отправляет сообщение в чат.
2. **Шаг 1** (`add_user_message`, синхронный, `queue=False`): мгновенно добавляет сообщение в чат, блокирует ввод.
3. **Шаг 2** (`bot_respond`, async generator): вызывает `InterviewSession.process_message()`:
    - записывает сообщение в последний `InterviewTurn`,
    - создаёт span `user_message` в Langfuse,
    - передаёт сообщение в `ObserverAgent.process()` вместе с последним вопросом интервьюера.
4. `ObserverAgent` возвращает `ObserverAnalysis`:
    - тип ответа (normal / hallucination / off_topic / question / stop_command / introduction / incomplete / excellent),
    - качество ответа, фактическую корректность, `is_gibberish`, `answered_last_question`,
    - извлечённые данные кандидата (опционально),
    - рекомендацию интервьюеру.
5. `InterviewSession` обновляет состояние (атомарно):
    - `candidate` (name/grade/tech stack) — идемпотентно,
    - корректирует `current_difficulty` (с сохранением для отката),
    - пишет span'ы `observer_analysis`, `candidate_info_update`, `difficulty_change`.
6. `InterviewerAgent.process()` генерирует следующий ответ/вопрос и возвращает внутренние мысли.
    - при ошибке — откат сложности, состояние не загрязняется.
7. При успехе: фиксация неидемпотентных мутаций (`covered_topics`, `confirmed_skills`, `knowledge_gaps`, счётчик ходов).
8. `InterviewSession` создаёт новый `InterviewTurn` с сообщением интервьюера и пишет span `interviewer_response`.
9. По команде остановки или лимиту ходов:
    - `EvaluatorAgent.process()` формирует `InterviewFeedback`,
    - пишется span `final_feedback`,
    - к трейсу добавляются финальные метрики (token metrics),
    - сохраняются логи.

---

## Агенты и взаимодействие

### BaseAgent

`src/app/agents/base.py`

- Общее для всех агентов:
    - `system_prompt` (абстрактное свойство),
    - сбор сообщений для LLM через `_build_messages()`,
    - формирование блока описания вакансии через `_build_job_description_block()`,
    - единый асинхронный интерфейс `process(...)`.

### ObserverAgent (анализ кандидата)

`src/app/agents/observer.py`

Задачи:

- определение типа ответа кандидата:
    - технический ответ, неполный ответ, отличный ответ,
    - встречный вопрос (role reversal),
    - уход от темы (off-topic),
    - галлюцинация / фактическая ошибка (по теме и не по теме вопроса),
    - бессмыслица (тест клавиатуры),
    - команда завершения.
- определение `answered_last_question` — ответил ли кандидат на активный технический вопрос.
- извлечение информации о кандидате из текста: имя, позиция, грейд, опыт, технологии.
- выдача рекомендаций интервьюеру с маркерами:
    - `ANSWERED=YES|NO`
    - `NEXT_STEP=ASK_NEW|REPEAT|FOLLOWUP`
    - `GIBBERISH_DETECTED=YES|NO`

Что задаётся в промпте (структурно, без текста):

- роль и миссия агента,
- определения `answered_last_question` и `is_gibberish`,
- правила классификации ответов и качества,
- правила детекции галлюцинаций и prompt injection,
- правила обработки встречных вопросов,
- правила адаптивности сложности,
- требование возвращать валидный JSON фиксированной схемы.

Retry-логика: при ошибке парсинга ответа LLM повторяет генерацию до `generation_retries` раз.

### InterviewerAgent (ведение интервью)

`src/app/agents/interviewer.py`

Задачи:

- ведение диалога и постановка ровно одного активного технического вопроса.
- генерация приветствия (`generate_greeting`) с учётом наличия описания вакансии.
- адаптация поведения по рекомендациям Observer:
    - исправление галлюцинаций (по теме → закрыть вопрос и задать новый; не по теме → переформулировать),
    - возврат с off-topic,
    - обработка бессмыслицы,
    - краткий ответ на встречный вопрос и возврат к активному вопросу,
    - уточняющие вопросы при неполном ответе,
    - усложнение при отличном ответе.
- соблюдение ограничения: вопросы только по технологиям, указанным кандидатом.

Что задаётся в промпте (структурно, без текста):

- роль и стиль общения,
- правила релевантности вопросов по стеку кандидата,
- правила «одного активного вопроса» (якоря) с условиями закрытия,
- правила обработки hallucination/off-topic/question/gibberish,
- правила безопасности (prompt injection),
- формат ответа (естественный текст, без JSON/markdown).

### EvaluatorAgent (финальный фидбэк)

`src/app/agents/evaluator.py`

Задачи:

- генерация финального `InterviewFeedback` в строгом JSON-формате:
    - вердикт (грейд, рекомендация по найму, уверенность),
    - технический обзор (подтверждённые навыки / пробелы),
    - soft skills (ясность, честность, вовлечённость),
    - персональный роадмап (темы, приоритеты, ресурсы),
    - общие комментарии.
- опора только на данные интервью (история диалога + сводка навыков).

Что задаётся в промпте (структурно, без текста):

- роль и миссия агента,
- запрет галлюцинаций в оценке (каждое утверждение должно быть подкреплено репликой из диалога),
- структура фидбэка и строгий формат JSON,
- критерии оценки (галлюцинации, вовлечённость, адекватность уровня, короткие интервью),
- ограничения безопасности.

Retry-логика: при ошибке парсинга ответа LLM повторяет генерацию до `generation_retries` раз.

---

## Структура проекта

Ключевые директории:

- `src/app/agents/` — агенты (Observer/Interviewer/Evaluator) и общий базовый класс.
- `src/app/agents/prompts/` — системные промпты агентов.
- `src/app/interview/` — сессия и логирование интервью.
- `src/app/llm/` — LLM клиент, парсер ответов, утилита моделей.
- `src/app/observability/` — Langfuse tracker и метрики токенов сессии.
- `src/app/core/` — конфигурация, константы, логирование, setup FastAPI.
- `src/app/ui/` — интерфейс и стили.
- `src/app/middleware/` — middleware (например client cache).
- `src/app/schemas/` — Pydantic модели интервью, фидбэка и настроек агентов.

---

## Требования

- Python 3.11
- Docker / Docker Compose (для контейнерного запуска)
- Redis (используется в docker-compose)

---

## Конфигурация (.env)

Файл `.env.example` содержит полный перечень переменных окружения. Основные:

### LiteLLM (подключение приложения к прокси)

- `LITELLM_BASE_URL` — базовый URL LiteLLM proxy.
- `LITELLM_API_KEY` — ключ доступа к LiteLLM.
- `LITELLM_MODEL` — модель по умолчанию (значение `model_name` из конфигурации LiteLLM).
- `LITELLM_TIMEOUT` — таймаут запросов.
- `LITELLM_MAX_RETRIES` — количество повторных попыток.
- `LITELLM_RETRY_BACKOFF_BASE` — базовая задержка для экспоненциального backoff.
- `LITELLM_RETRY_BACKOFF_MAX` — максимальная задержка для экспоненциального backoff.
- `LITELLM_MODELS_FETCH_TIMEOUT` — таймаут запроса списка доступных моделей.

### Интервью

- `INTERVIEW_LOG_DIR` — директория для логов интервью.
- `TEAM_NAME` — имя команды.
- `MAX_TURNS` — лимит ходов интервью.
- `HISTORY_WINDOW_TURNS` — количество последних ходов, передаваемых в контекст LLM Interviewer.
- `GREETING_MAX_TOKENS` — максимальное количество токенов для генерации приветствия.

### Redis

- `REDIS_CACHE_HOST`
- `REDIS_CACHE_PORT`

### Langfuse (self-hosted / локально)

- `LANGFUSE_ENABLED` — включить/выключить Langfuse трекинг.
- `LANGFUSE_HOST` — URL Langfuse для SDK:
    - в Docker Compose: `http://langfuse:3000`,
    - при локальном запуске без Compose: обычно `http://localhost:3000`.
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` — ключи Langfuse (создаются в UI: Settings → API Keys).
- Переменные контейнера Langfuse в `docker-compose.yml`:
    - `DATABASE_URL`, `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, `SALT`, `TELEMETRY_ENABLED`.

### Приложение и логирование

- `APP_NAME`, `APP_DESCRIPTION`, `APP_VERSION`, `LICENSE_NAME`, `CONTACT_NAME`, `CONTACT_EMAIL`
- `CLIENT_CACHE_MAX_AGE` — max-age для `Cache-Control`.
- `APP_TZ_OFFSET` — смещение TZ для логов.
- `APP_LOG_DIR` — директория логов приложения.

---

## LiteLLM шлюз (llm-gateway-litellm)

В репозитории есть отдельный шлюз **LiteLLM** для OpenAI-compatible API маршрутизации к нескольким бэкендам (локальным
и облачным), с хранением конфигурации моделей и логов в PostgreSQL.

Директория: `llm-gateway-litellm/`

### Что поднимается

- **LiteLLM** (контейнер `litellm`) — OpenAI-compatible API + маршрутизация запросов + healthchecks.
- **PostgreSQL** (контейнер `litellm_db`) — хранение моделей/настроек/логов при включённом `STORE_MODEL_IN_DB`.

### Быстрый старт LiteLLM

```bash
cd llm-gateway-litellm
cp .env.example .env
docker compose up -d
```

Остановка:

```bash
docker compose down
```

### Основные переменные окружения LiteLLM

Файл `llm-gateway-litellm/.env.example` содержит полный набор параметров.

### Конфигурация моделей LiteLLM

Файл `llm-gateway-litellm/config.yaml` задаёт:

- `model_list` — список моделей (значения используются в поле `model` запросов).
- `general_settings.store_model_in_db: true` — хранить модели в БД.
- `litellm_settings` — таймауты и формат логов.

### Как подключить Interview Coach к LiteLLM шлюзу

1. Поднимите LiteLLM шлюз (см. шаги выше).
2. В корневом `.env` проекта укажите параметры подключения:

- `LITELLM_BASE_URL=http://localhost:4000` (или ваш `${LITELLM_PORT_EXTERNAL}`)
- `LITELLM_API_KEY=<LITELLM_MASTER_KEY>`
- `LITELLM_MODEL=local_llm` (или `cloud/deepseek-chat`, `cloud/deepseek-coder`, `cloud/deepseek-reasoner`)

---

## Запуск в Docker Compose

### 1) Подготовка `.env`

Скопировать пример и заполнить:

```bash
cp .env.example .env
```

Минимально для Langfuse:

- установите `LANGFUSE_ENABLED=true`,
- создайте API ключи в Langfuse UI и заполните `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`.

### 2) Запуск

```bash
docker compose up --build
```

### 3) Доступные сервисы (по умолчанию)

| Сервис | Адрес | Описание |
|--------|-------|----------|
| **Gradio UI** | [http://localhost:7860](http://localhost:7860) | Веб-интерфейс для проведения интервью |
| **Nginx → FastAPI** | [http://localhost:90](http://localhost:90) | Проксирует запросы к FastAPI backend |
| **FastAPI docs** | [http://localhost:90/docs](http://localhost:90/docs) | Swagger UI (OpenAPI документация) |
| **FastAPI redoc** | [http://localhost:90/redoc](http://localhost:90/redoc) | ReDoc (альтернативная документация) |
| **Langfuse UI** | [http://localhost:3000](http://localhost:3000) | Observability: трейсы, метрики, LLM-вызовы |
| **FastAPI backend** | `backend:8000` (внутри сети compose) | Не доступен извне напрямую |
| **Redis** | `redis_cache:6379` (внутри сети compose) | Кэш, не доступен извне |
| **Langfuse DB** | `langfuse-db:5432` (внутри сети compose) | PostgreSQL, не доступен извне |

> Порты настраиваются через переменные окружения в `.env`:
> `GRADIO_PORT`, `NGINX_EXTERNAL_PORT`, `BACKEND_PORT`, `LANGFUSE_PORT`.

---

## Langfuse (observability)

### Что трекается

В проекте добавлен self-hosted Langfuse для трекинга и метрик:

- trace на каждую сессию интервью (session_id),
- generation на каждый LLM вызов (observer/interviewer/evaluator),
- span'ы ключевых этапов:
    - `greeting`, `user_message`, `observer_analysis`, `interviewer_response`, `final_feedback`,
    - `candidate_info_update` (при извлечении данных кандидата),
    - `difficulty_change` (если менялась сложность),
    - `session_token_metrics` (финальные метрики).
- score'ы на трейс:
    - `total_tokens`, `total_turns`, `llm_calls`, `avg_tokens_per_turn`,
    - `confidence_score` (вес: confidence_score/100).

### Где в коде

- `src/app/observability/langfuse_client.py` — `LangfuseTracker` + `SessionMetrics`.
- `src/app/llm/client.py` — создаёт Langfuse generation на каждый вызов LLM.
- `src/app/interview/session.py` — создаёт trace, добавляет span'ы и сохраняет метрики в лог.

### Как отключить

Установить `LANGFUSE_ENABLED=false`.

Также трекинг автоматически отключится, если ключи не заданы (см. логи старта приложения).

---

## Использование

### Через Web UI

1. Нажать «Начать интервью».
2. Представиться (имя, позиция/роль, опыт, технологии).
3. Отвечать на вопросы.
4. Ввести «стоп» для завершения и генерации фидбэка (или нажать кнопку «Завершить»).

### Выходные артефакты

После завершения формируются файлы в `INTERVIEW_LOG_DIR`:

- `interview_log_YYYYMMDD_HHMMSS.json` — основной лог по формату ТЗ.
- `interview_detailed_YYYYMMDD_HHMMSS.json` — детальный лог с внутренними мыслями.
    - содержит `token_metrics` (суммарные токены, токены по агентам, средние значения).

В UI в финальный фидбэк дополнительно добавляется блок «📊 МЕТРИКИ СЕССИИ (ТОКЕНЫ)».

---

## Логирование

- Ротация файлов:
    - `system.log` — сообщения с `log_type=SYSTEM`.
    - `personal.log` — сообщения с `log_type=PERSONAL` и `ID:<request_id>`.
- Консольные логи включают внешние библиотеки с `log_type=EXTERNAL`.
- Временные метки форматируются в TZ, заданном `APP_TZ_OFFSET`.

---

## Разработка

### pre-commit

Репозиторий содержит `.pre-commit-config.yaml`:

- форматирование: `black`, `isort`
- линтинг: `flake8`
- типы: `mypy`
- проверка файлов: yaml/json/toml, trailing whitespace, debug statements и др.

Запуск:

```bash
pre-commit install
pre-commit run --all-files
```

---

## Демонстрация работы

Ниже приведены ключевые экраны, демонстрирующие работу системы и сбор метрик.

### Скриншот веб-интерфейса

![chat](assets/ui_chat.png)

### Результаты после завершения интервью

![feedback](assets/ui_feedback.png)

### Langfuse — Sessions (метрики по интервью-сессиям)

![langfuse_sessions](assets/langfuze_session.png)

### Langfuse — Generations (вызовы LLM и полезная диагностика)

![langfuse_generations](assets/langfuse_generations.png)

### LiteLLM — Usage (потребление токенов)

![litellm_usage](assets/litellm_usage.png)

---

## Что НЕ входит в PoC

Текущая версия является Proof of Concept. Следующие возможности **не реализованы** и планируются для будущих итераций:

1. **Multi-user и аутентификация.** Система рассчитана на одного пользователя за раз. Нет регистрации, авторизации, разделения сессий между пользователями.
2. **Персистентность сессий.** Состояние интервью хранится в памяти. При перезапуске контейнера все активные сессии теряются. История прошлых интервью не сохраняется для повторного анализа.
3. **Мультиязычность.** Интервью проводится только на русском языке. Поддержка английского и других языков отсутствует.
4. **Продвинутая аналитика и дашборды.** Нет агрегированной статистики по нескольким интервью, трендов прогресса кандидата, сравнения с другими кандидатами.
5. **Интеграция с внешними платформами.** Нет интеграции с GitHub, LinkedIn, HH.ru или системами отслеживания кандидатов (ATS).
6. **Голосовой режим.** Поддерживается только текстовый чат. Распознавание речи и синтез голоса не реализованы.
7. **Автоматическое масштабирование.** Нет горизонтального масштабирования, auto-scaling, load balancing между несколькими инстансами.