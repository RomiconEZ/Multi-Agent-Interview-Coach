# DOC.md — Документация по проекту Multi-Agent Interview Coach

Документ описывает устройство проекта, потоки данных, модели, конфигурацию, логирование и точки расширения.

---

## 1. Назначение

Проект реализует интерактивное техническое интервью в чат-формате:

- пользователь (кандидат) отвечает на вопросы,
- система анализирует ответы и управляет диалогом через мультиагентную архитектуру,
- по завершении формирует структурированный финальный фидбэк и сохраняет логи.

Интеграция с LLM выполняется через LiteLLM proxy, запросы идут на OpenAI-compatible endpoint `/v1/chat/completions`.

Дополнительно используется Langfuse (self-hosted / локальный) для observability: трекинг трейсов интервью,
LLM generation, ошибок и метрик токенов.

---

## 2. Компоненты и ответственность

### 2.1 UI слой (Gradio)

Файлы:

- `src/app/ui/gradio_app.py` — логика интерфейса и обработчики событий.
- `src/app/ui/styles.py` — CSS-стили (`MAIN_CSS`) и HTML-разметка хедера (`HEADER_HTML`).

Ответственность:

- создание UI (chatbot, input, кнопки start/stop/reset, вкладки «Интервью» и «Фидбэк»),
- запуск/остановка/сброс интервью-сессии,
- двухшаговый паттерн отправки сообщений (мгновенное обновление UI + асинхронная генерация),
- отображение метрик токенов в финальном фидбэке,
- выдача ссылок на сохранённые логи через `gr.File`.

Паттерн обработки сообщений:

1. **Шаг 1** (`add_user_message`, `queue=False`, синхронный): мгновенно добавляет сообщение пользователя в чат, очищает
   и блокирует ввод, обновляет статус. Не вызывает LLM.
2. **Шаг 2** (`bot_respond`, `.then(...)`, async generator): обрабатывает сообщение через LLM-агенты, возвращает ответ.
   При завершении интервью — двухэтапный yield: сначала «Формирую фидбэк...», затем итоговый результат с фидбэком.

Ключевые функции:

- `_start_interview_async()` / `start_interview()`: создание сессии, генерация приветствия.
- `add_user_message()`: мгновенное обновление UI (шаг 1).
- `bot_respond()`: async generator, обработка через LLM (шаг 2).
- `stop_interview()`: async generator, принудительная остановка и генерация фидбэка.
- `reset_interview()`: сброс сессии и очистка UI.
- `refresh_models()`: обновление списка моделей из LiteLLM API.

Глобальное состояние:

- `_current_session: InterviewSession | None`
- `_last_log_path`, `_last_detailed_log_path` — пути к последним сохранённым логам.

---

### 2.2 Оркестрация (InterviewSession)

Файл: `src/app/interview/session.py`

Ответственность:

- управление жизненным циклом интервью,
- хранение последнего сообщения интервьюера (`_last_agent_message`) как активного «якоря»,
- последовательный вызов агентов (Observer → Interviewer → Evaluator),
- обновление `InterviewState` с гарантией атомарности мутаций,
- адаптация сложности вопросов с откатом при сбое Interviewer,
- сохранение логов через `InterviewLogger`,
- интеграция с Langfuse:
    - создание trace на сессию,
    - запись span'ов и score'ов,
    - сбор метрик токенов и добавление их в детальный лог.

Ключевые методы:

- `start()`:
    - создаёт `InterviewState` (с опциональным `job_description`),
    - создаёт Langfuse trace (session_id),
    - получает приветствие через `InterviewerAgent.generate_greeting()`,
    - создаёт `InterviewTurn`,
    - пишет span `greeting`.

- `process_message(user_message)`:
  Порядок обработки обеспечивает атомарность мутаций состояния:
    1. Записывает ответ кандидата в последний `InterviewTurn`.
    2. Пишет span `user_message`.
    3. **Stage 1 — Observer**: вызывает `ObserverAgent.process()` для анализа. При ошибке — возврат сообщения об ошибке
       без мутаций состояния.
    4. **Stage 2 — Идемпотентное обновление**: обновляет информацию о кандидате из `extracted_info` (идемпотентная
       операция).
    5. **Stage 3 — Стоп-команда**: при `STOP_COMMAND` — завершает интервью.
    6. **Stage 4 — Корректировка сложности**: применяет `adjust_difficulty()` только если `answered_last_question=True`.
       Сохраняет состояние для возможного отката.
    7. **Stage 5 — Interviewer**: вызывает `InterviewerAgent.process()`. При ошибке — **откатывает** корректировку
       сложности к сохранённому состоянию.
    8. **Stage 6 — Фиксация**: неидемпотентные мутации (topics, skills, gaps, turn counter) применяются **только при
       полном успехе** обоих агентов.

- `generate_feedback()`:
    - вызывает `EvaluatorAgent.process()`,
    - пишет span `final_feedback`,
    - добавляет финальные метрики сессии к трейсу,
    - сохраняет summary и detailed лог,
    - дописывает `token_metrics` в детальный лог.

---

### 2.3 Агенты (Observer / Interviewer / Evaluator)

Файлы:

- `src/app/agents/base.py` — абстрактный базовый класс.
- `src/app/agents/observer.py` — агент-наблюдатель.
- `src/app/agents/interviewer.py` — агент-интервьюер.
- `src/app/agents/evaluator.py` — агент-оценщик.
- `src/app/agents/prompts/` — системные промпты агентов.

Общее:

- все агенты наследуются от `BaseAgent`,
- у каждого агента есть `system_prompt` (абстрактное свойство),
- запросы к LLM идут через `LLMClient`,
- Observer и Evaluator поддерживают `generation_retries` — повторные попытки генерации при ошибке парсинга,
- общий метод `_build_messages()` обеспечивает корректное чередование ролей в истории,
- общий метод `_build_job_description_block()` формирует блок описания вакансии для контекста.

---

### 2.4 LLM клиент и утилиты

Файлы:

- `src/app/llm/client.py` — HTTP-клиент к LiteLLM proxy.
- `src/app/llm/response_parser.py` — парсер ответов LLM (извлечение JSON и reasoning из текста).
- `src/app/llm/models.py` — получение списка доступных моделей из LiteLLM API.

`response_parser` поддерживает многоуровневую стратегию извлечения JSON из ответа LLM:

1. `<r>...</r>` теги (приоритетный формат).
2. `<result>...</result>` теги.
3. Markdown code block (` ```json ... ``` `).
4. Сырой JSON-объект `{...}` с поиском сбалансированных скобок.

`models.py` предоставляет:

- `fetch_available_models()` — async версия.
- `fetch_available_models_sync()` — sync версия (для UI при инициализации).
- `get_models_for_ui()` — обёртка с fallback на модель по умолчанию.

---

### 2.5 Observability (Langfuse)

Файл: `src/app/observability/langfuse_client.py`

Ответственность:

- создание trace и generation (через SDK Langfuse),
- сбор токен-метрик по сессии и по агентам (Observer / Interviewer / Evaluator),
- сохранение агрегированных метрик в памяти на время жизни процесса,
- добавление финальных метрик в trace и в детальные логи интервью.

Ключевые сущности:

- `LangfuseTracker` — фасад над Langfuse SDK (singleton через `get_langfuse_tracker()`).
- `SessionMetrics` — агрегатор метрик сессии.
- `TokenUsage` — структура для подсчёта input/output/total токенов.

Где создаются метрики:

- `LLMClient.complete(...)` — после каждого ответа обновляет `SessionMetrics.add_generation(...)`
  через `LangfuseTracker.end_generation(..., usage=..., session_id=..., generation_name=...)`.
- `InterviewSession.process_message(...)` — увеличивает счётчик ходов `LangfuseTracker.increment_turn(session_id)`.
- `InterviewSession.generate_feedback(...)` — финализирует трейсы и сохраняет метрики в логи.

---

## 3. Последовательность обработки (sequence)

Ниже приведён детерминированный порядок действий при одном сообщении кандидата:

```
Gradio UI
  ├─ add_user_message()  [queue=False, sync — мгновенное обновление UI]
  └─ bot_respond()       [async generator — обработка через LLM]
      └─ InterviewSession.process_message(user_message)
          ├─ state.turns[-1].user_message = user_message
          ├─ LangfuseTracker.add_span(name="user_message")
          │
          │  ── Stage 1: Observer ──
          ├─ ObserverAgent.process(state, user_message, last_question)
          │    └─ LLMClient.complete(...) -> ObserverAnalysis (+ generation в Langfuse)
          ├─ LangfuseTracker.add_span(name="observer_analysis")
          │
          │  ── Stage 2: Идемпотентное обновление ──
          ├─ InterviewSession._update_candidate_info(extracted_info)
          │    └─ (опционально) LangfuseTracker.add_span(name="candidate_info_update")
          │
          │  ── Stage 3: Стоп-команда ──
          ├─ [если STOP_COMMAND] → завершение интервью, return
          │
          │  ── Stage 4: Корректировка сложности (с сохранением для отката) ──
          ├─ [если answered_last_question] InterviewState.adjust_difficulty(analysis)
          │    └─ (опционально) LangfuseTracker.add_span(name="difficulty_change")
          │
          │  ── Stage 5: Interviewer ──
          ├─ InterviewerAgent.process(state, analysis, user_message)
          │    └─ LLMClient.complete(...) -> (reply_text, thoughts) (+ generation в Langfuse)
          │    └─ [при ошибке] → откат difficulty к saved_difficulty, return ошибку
          │
          │  ── Stage 6: Фиксация (только при полном успехе) ──
          ├─ LangfuseTracker.increment_turn(session_id)
          ├─ InterviewSession._update_state_from_analysis(analysis, user_message)
          │    └─ covered_topics, confirmed_skills, knowledge_gaps
          ├─ InterviewSession sets _last_agent_message = response
          ├─ InterviewSession adds thoughts to last turn
          ├─ InterviewSession creates next InterviewTurn with interviewer message
          └─ LangfuseTracker.add_span(name="interviewer_response")
```

Завершение:

- если `analysis.response_type == STOP_COMMAND` → интервью завершается сразу и вызывается `generate_feedback()`;
- если достигнут лимит `MAX_TURNS` → интервью завершается и формируется фидбэк.

---

## 4. «Активный технический вопрос» (якорь)

Система опирается на правило, что в интервью существует один активный вопрос — последнее сообщение интервьюера,
ожидающее ответа кандидата.

Реализация:

- `InterviewSession` хранит `_last_agent_message`.
- `ObserverAgent` получает `last_question` и определяет `answered_last_question`:
    - `True` — кандидат закрыл вопрос (ответил, ошибся по теме, отказался).
    - `False` — вопрос остаётся открытым (off-topic, встречный вопрос, бессмыслица, галлюцинация не по теме).
- `InterviewerAgent` получает в контексте «АКТИВНЫЙ ЯКОРЬ» и обязан возвращаться к нему при:
    - встречных вопросах,
    - off-topic,
    - бессмыслице (gibberish),
    - галлюцинациях не по теме вопроса.

Логика определения `answered_last_question` (файл `observer.py`, функция `_resolve_answered_last_question`):

1. Бессмыслица (`is_gibberish=True`) → всегда `False`.
2. Явное значение от LLM (если тип `bool`) → используется напрямую.
3. Fallback по `response_type` через `UNANSWERED_RESPONSE_TYPES` (OFF_TOPIC, QUESTION, STOP_COMMAND → `False`).

---

## 5. Адаптация сложности

Сущности:

- `DifficultyLevel` (BASIC/INTERMEDIATE/ADVANCED/EXPERT) — `src/app/schemas/interview.py`.
- `InterviewState.adjust_difficulty(analysis)`:
    - увеличивает сложность после серии хороших ответов (streak ≥ 2),
    - уменьшает после серии плохих (streak ≥ 2),
    - сбрасывает streak при отсутствии сигналов.

Сигналы:

- `ObserverAnalysis.should_increase_difficulty`
- `ObserverAnalysis.should_simplify`

Ограничения:

- Если `answered_last_question=False` — оба флага принудительно ставятся в `False` (файл `observer.py`). Нельзя менять
  сложность, если кандидат не ответил на вопрос.
- В `process_message()` корректировка сложности применяется **до** вызова Interviewer (нужна для контекста), но *
  *откатывается** при сбое Interviewer для сохранения консистентности состояния.

---

## 6. Данные и модели (schemas)

### 6.1 Состояние интервью

Файл: `src/app/schemas/interview.py`

- `CandidateInfo`: имя, позиция, целевой грейд, опыт, технологии.
- `InterviewTurn`: один ход интервью (сообщение интервьюера, сообщение кандидата, мысли агентов, timestamp).
- `InterviewState`: агрегирует историю ходов, навыки, пробелы, текущую сложность.

Ключевые поля `InterviewState`:

- `turns: list[InterviewTurn]`
- `current_difficulty: DifficultyLevel`
- `covered_topics: list[str]`
- `confirmed_skills: list[str]`
- `knowledge_gaps: list[dict[str, str | None]]`
- `consecutive_good_answers: int` / `consecutive_bad_answers: int`
- `job_description: str | None`

Вспомогательные типы:

- `ResponseType` — тип ответа (NORMAL, HALLUCINATION, OFF_TOPIC, QUESTION, STOP_COMMAND, INTRODUCTION, INCOMPLETE,
  EXCELLENT).
- `AnswerQuality` — качество ответа (EXCELLENT, GOOD, ACCEPTABLE, POOR, WRONG).
- `DifficultyLevel` — уровень сложности (BASIC, INTERMEDIATE, ADVANCED, EXPERT).
- `GradeLevel` — уровень кандидата (INTERN, JUNIOR, MIDDLE, SENIOR, LEAD).
- `UNANSWERED_RESPONSE_TYPES` — `frozenset` типов ответов, при которых кандидат не отвечает на вопрос.

---

### 6.2 Аналитика ObserverAgent

- `ObserverAnalysis`: тип ответа, качество, фактическая корректность, `is_gibberish`, `answered_last_question`, темы,
  рекомендация, `correct_answer`, `extracted_info`, `demonstrated_level`, флаги сложности.
- `ExtractedCandidateInfo`: имя, позиция, грейд, опыт, технологии (извлекается из текста кандидата).
- `InternalThought`: мысль агента (from_agent, to_agent, content, timestamp).

---

### 6.3 Финальный фидбэк

Файл: `src/app/schemas/feedback.py`

- `InterviewFeedback` содержит:
    - `verdict: Verdict` (grade, hiring_recommendation, confidence_score)
    - `technical_review: TechnicalReview` (confirmed_skills, knowledge_gaps)
    - `soft_skills_review: SoftSkillsReview` (clarity, honesty, engagement)
    - `roadmap: PersonalRoadmap` (items, summary)
    - `general_comments: str`

Метод `InterviewFeedback.to_formatted_string()` формирует человекочитаемый отчёт для UI и логов.

---

### 6.4 Конфигурация агентов

Файл: `src/app/schemas/agent_settings.py`

- `SingleAgentConfig`: temperature, max_tokens, generation_retries.
- `AgentSettings`: конфигурации для Observer, Interviewer, Evaluator.
- `InterviewConfig`: модель, макс. ходов, описание вакансии, настройки агентов.

---

## 7. Форматы логов интервью

Файл: `src/app/interview/logger.py`

### 7.1 Основной лог (формат по ТЗ)

Имя файла: `interview_log_YYYYMMDD_HHMMSS.json`

Содержимое (модель `InterviewLog`):

- `turns`: массив объектов `turn_id`, `agent_visible_message`, `user_message`, `internal_thoughts` (строка, формат
  `[agent_name]: <thought>\n`).
- `final_feedback`: строка (форматированный отчёт) или `null`.

### 7.2 Детальный лог

Имя файла: `interview_detailed_YYYYMMDD_HHMMSS.json`

Содержимое:

- `candidate_info`: name/position/target_grade/experience/technologies.
- `interview_stats`: total_turns, final_difficulty, confirmed_skills, knowledge_gaps, covered_topics.
- `turns`: список ходов с `timestamp` и полным `internal_thoughts` (массив dict).
- `final_feedback`: `model_dump()` объекта `InterviewFeedback` или `null`.
- `token_metrics` (добавляется после генерации фидбэка):
    - total токены, токены по агентам, количество ходов и генераций, средние значения.

---

## 8. LLM интеграция

Файл: `src/app/llm/client.py`

- Запросы идут в LiteLLM proxy: `POST /v1/chat/completions`.
- `LLMClient.complete(...)` — возвращает текстовый ответ. Поддерживает:
    - экспоненциальный backoff с конфигурируемыми `retry_backoff_base` / `retry_backoff_max`,
    - retry на HTTP коды 429, 500, 502, 503, 504,
    - опциональный `json_mode` (через `response_format`).
- `LLMClient.complete_json(...)` — ожидает JSON-ответ. Автоматически переключается на текстовый режим если модель не
  поддерживает `response_format` (кешируется).

Параметры:

- `model` — из конфигурации или из параметра `create_interview_session(model)`.
- `temperature`, `max_tokens` — задаются на уровне вызовов агентов.
- `timeout`, `max_retries`, `retry_backoff_base`, `retry_backoff_max` — из `.env`.

---

### 8.1 Парсер ответов LLM

Файл: `src/app/llm/response_parser.py`

Функции:

- `extract_json_from_llm_response(text)` — извлечение JSON по приоритету: `<r>` → `<result>` → markdown code block →
  сырой `{...}`.
- `extract_reasoning_from_llm_response(text)` — извлечение блока `<reasoning>...</reasoning>`.

Используется Observer и Evaluator для парсинга структурированных ответов LLM.

---

### 8.2 Langfuse интеграция (observability)

#### 8.2.1 Конфигурация

Файл: `src/app/core/config.py`

Переменные окружения:

- `LANGFUSE_ENABLED` — включить/выключить трекинг.
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` — ключи API.
- `LANGFUSE_HOST` — хост Langfuse:
    - в Docker Compose: `http://langfuse:3000`,
    - локально: обычно `http://localhost:3000`.

Особенность:

- если `LANGFUSE_ENABLED=true`, но ключи не заданы, трекинг отключается автоматически (логируется при инициализации).

#### 8.2.2 Trace / Generation модель

- Trace создаётся на старте интервью-сессии и живёт до конца `generate_feedback()`.
- Generation создаётся на каждый LLM вызов (Observer / Interviewer / Evaluator) с именем `generation_name`
  (например `observer_analysis`, `interviewer_response`, `interviewer_greeting`, `evaluator_feedback`).
- Usage (prompt_tokens / completion_tokens / total_tokens) берётся из ответа OpenAI-compatible API (`usage`)
  и сохраняется в `SessionMetrics`.

#### 8.2.3 Метрики сессии

`SessionMetrics` агрегирует:

- `total_usage` и `by_agent` (observer/interviewer/evaluator),
- количество ходов (`turn_count`) и LLM вызовов (`generation_count`),
- средние значения.

Финализация:

- `LangfuseTracker.add_session_metrics_to_trace(...)` добавляет span с полной структурой метрик и score'ы.
- Метрики также сохраняются в детальный лог интервью (`token_metrics`).

---

## 9. Конфигурация приложения

Файл: `src/app/core/config.py`

- Используется `pydantic-settings`.
- Настройки сгруппированы в несколько классов:
    - `AppSettings`, `EnvironmentSettings`, `RedisCacheSettings`, `ClientSideCacheSettings`,
      `LogSettings`, `LiteLLMSettings`, `InterviewSettings`, `LangfuseSettings`, `GradioUISettings`.
- Все объединено в `Settings`, доступно как `settings = Settings()`.

Особенности:

- `APP_LOG_DIR` и `INTERVIEW_LOG_DIR` создаются при валидации.
- Есть вычисляемые поля `SYSTEM_LOG_PATH`, `PERSONAL_LOG_PATH`, `REDIS_CACHE_URL`.
- `GradioUISettings` содержит параметры компоновки UI, диапазоны слайдеров и значения по умолчанию для параметров
  агентов в интерфейсе.

---

## 10. FastAPI приложение

Файлы:

- `src/app/main.py`
- `src/app/core/setup.py`
- `src/app/api/*`

Особенности сборки:

- middleware `ClientCacheMiddleware` добавляет `Cache-Control: public, max-age=...`.
- документация добавляется отдельным router (маршруты `/docs`, `/redoc`, `/openapi.json`).
- в docker-compose предусмотрен Nginx как внешний прокси.

---

## 11. Docker окружение

Файлы:

- `docker-compose.yml`
- `Dockerfile` (backend)
- `Dockerfile.gradio` (UI)

### 11.1 Backend (gunicorn + uvicorn worker)

- количество воркеров вычисляется от `nproc` и `RESERVED_CPUS`.
- запуск: `gunicorn -k uvicorn.workers.UvicornWorker app.main:app`.

### 11.2 Gradio

- запуск: `python -m app.gradio_main --host 0.0.0.0 --port 7860`.

### 11.3 Langfuse + PostgreSQL (self-hosted)

Сервисы:

- `langfuse-db` — PostgreSQL 15.
- `langfuse` — Langfuse UI/API.

Ключевые переменные:

- `DATABASE_URL` — подключение к `langfuse-db`.
- `NEXTAUTH_SECRET`, `NEXTAUTH_URL`, `SALT` — обязательные параметры рантайма Langfuse.

Порт UI:

- пробрасывается на хост: `${LANGFUSE_PORT:-3000}:3000`.

---

## 12. Безопасность и устойчивость диалога

Механизмы на уровне промптов и пайплайна:

- игнорирование prompt injection в блоках `<user_input>` (описано в промптах Observer/Interviewer),
- сохранение активного вопроса при role reversal / off-topic / hallucination / gibberish,
- детекция бессмысленных сообщений (`is_gibberish`) с соответствующей реакцией,
- фиксация чувствительных ключей в `SENSITIVE_KEYS` (модуль `src/app/core/constants.py`) для потенциального
  использования при редактировании логов запросов/ответов,
- атомарность мутаций состояния: неидемпотентные изменения применяются только при полном успехе всех агентов, с откатом
  сложности при сбое Interviewer.

---

## 13. Точки расширения

### 13.1 Новые API endpoints

- Добавлять роутеры в `src/app/api/v1/` и подключать в `src/app/api/v1/__init__.py`.

### 13.2 Новые агенты

- Создать класс-наследник `BaseAgent`.
- Определить `system_prompt` и `process(...)`.
- Добавить промпт в `src/app/agents/prompts/`.
- Подключить в `src/app/agents/__init__.py` и при необходимости — в `InterviewSession`.

### 13.3 Новые форматы логов

- Расширять `InterviewLogger` (при необходимости — добавлять дополнительные файлы/форматы).
- Не нарушать текущий формат `InterviewLog` для совместимости.

### 13.4 Новые источники состояния/хранилища

- Redis подключается в lifespan FastAPI (`create_redis_cache_pool`).
- Переиспользовать `src/app/utils/cache.py` как точку доступа к клиенту Redis.

---

## 14. Быстрые проверки работоспособности

- UI: старт интервью → отправка сообщения → проверка появления ответа.
- Завершение: команда `стоп` → получение фидбэка → проверка появления файлов логов в `INTERVIEW_LOG_DIR`.
- Langfuse: наличие trace на сессию, generation на LLM вызовы, span'ы ключевых этапов.
- Логи приложения: наличие `system.log` и `personal.log` в `APP_LOG_DIR`.

---

## 15. Приложение: таблица ключевых файлов

| Назначение               | Путь                                       |
|--------------------------|--------------------------------------------|
| UI (Gradio) — логика     | `src/app/ui/gradio_app.py`                 |
| UI (Gradio) — стили      | `src/app/ui/styles.py`                     |
| Оркестрация интервью     | `src/app/interview/session.py`             |
| Логи интервью            | `src/app/interview/logger.py`              |
| Агенты                   | `src/app/agents/*`                         |
| Промпты агентов          | `src/app/agents/prompts/*`                 |
| LLM клиент               | `src/app/llm/client.py`                    |
| Парсер ответов LLM       | `src/app/llm/response_parser.py`           |
| Утилита моделей LLM      | `src/app/llm/models.py`                    |
| Observability (Langfuse) | `src/app/observability/langfuse_client.py` |
| Схемы: интервью          | `src/app/schemas/interview.py`             |
| Схемы: фидбэк            | `src/app/schemas/feedback.py`              |
| Схемы: настройки агентов | `src/app/schemas/agent_settings.py`        |
| Конфигурация             | `src/app/core/config.py`                   |
| Логирование              | `src/app/core/logger_setup.py`             |
| FastAPI setup            | `src/app/core/setup.py`                    |
| Docker Compose           | `docker-compose.yml`                       |
| Backend Dockerfile       | `Dockerfile`                               |
| Gradio Dockerfile        | `Dockerfile.gradio`                        |