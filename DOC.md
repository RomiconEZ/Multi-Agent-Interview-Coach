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

Файл: `src/app/ui/gradio_app.py`

Ответственность:
- создание UI (chatbot, input, кнопки start/stop, вывод фидбэка),
- запуск/остановка интервью-сессии,
- синхронные обёртки вокруг async-логики (`_run_async`),
- выдача ссылок на сохранённые логи через `gr.File`,
- отображение метрик токенов в финальном фидбэке (добавляется после генерации фидбэка).

Ключевые элементы:
- `_current_session: InterviewSession | None`
- `_start_interview_async()`: создание сессии, генерация приветствия.
- `_send_message_async()`: обработка пользовательского сообщения.
- `_stop_interview_async()`: принудительная остановка и генерация фидбэка.

---

### 2.2 Оркестрация (InterviewSession)

Файл: `src/app/interview/session.py`

Ответственность:
- управление жизненным циклом интервью,
- хранение последнего сообщения интервьюера (`_last_agent_message`) как активного «якоря»,
- последовательный вызов агентов (Observer → Interviewer → Evaluator),
- обновление `InterviewState`,
- адаптация сложности вопросов,
- сохранение логов через `InterviewLogger`,
- интеграция с Langfuse:
  - создание trace на сессию,
  - запись span’ов и score’ов,
  - сбор метрик токенов и добавление их в детальный лог.

Ключевые методы:
- `start()`:
  - создаёт `InterviewState`,
  - создаёт Langfuse trace (session_id),
  - получает приветствие через `InterviewerAgent.generate_greeting()`,
  - создаёт `InterviewTurn`,
  - пишет span `greeting`.
- `process_message(user_message)`:
  - записывает ответ кандидата в последний `InterviewTurn`,
  - увеличивает счётчик ходов для метрик Langfuse,
  - пишет span `user_message`,
  - вызывает `ObserverAgent.process()` для анализа,
  - обновляет состояние (данные кандидата, темы, пробелы),
  - корректирует `current_difficulty` и пишет span `difficulty_change` при изменении,
  - вызывает `InterviewerAgent.process()` для генерации следующей реплики,
  - создаёт следующий `InterviewTurn`,
  - пишет span `interviewer_response`,
  - завершает интервью по `stop_command` или `MAX_TURNS`.
- `generate_feedback()`:
  - вызывает `EvaluatorAgent.process()`,
  - пишет span `final_feedback`,
  - добавляет финальные метрики сессии к трейсу,
  - сохраняет summary и detailed лог,
  - дописывает `token_metrics` в детальный лог.

---

### 2.3 Агенты (Observer / Interviewer / Evaluator)

Файлы:
- `src/app/agents/base.py`
- `src/app/agents/observer.py`
- `src/app/agents/interviewer.py`
- `src/app/agents/evaluator.py`

Общее:
- все агенты наследуются от `BaseAgent`,
- у каждого агента есть `system_prompt`,
- запросы к LLM идут через `LLMClient`.

---

### 2.4 Observability (Langfuse)

Файл: `src/app/observability/langfuse_client.py`

Ответственность:
- создание trace и generation (через SDK Langfuse),
- сбор токен-метрик по сессии и по агентам (Observer / Interviewer / Evaluator),
- сохранение агрегированных метрик в памяти на время жизни процесса,
- добавление финальных метрик в trace и в детальные логи интервью.

Ключевые сущности:
- `LangfuseTracker` — фасад над Langfuse SDK.
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
  └─ send_message()
      └─ InterviewSession.process_message(user_message)
          ├─ LangfuseTracker.increment_turn(session_id)
          ├─ LangfuseTracker.add_span(name="user_message")
          ├─ ObserverAgent.process(state, user_message, last_question)
          │    └─ LLMClient.complete(...) -> ObserverAnalysis (+ generation в Langfuse)
          ├─ LangfuseTracker.add_span(name="observer_analysis")
          ├─ InterviewSession._update_candidate_info(extracted_info)
          ├─ InterviewSession._update_state_from_analysis(analysis, user_message)
          ├─ InterviewState.adjust_difficulty(analysis)
          │    └─ (опционально) LangfuseTracker.add_span(name="difficulty_change")
          ├─ InterviewerAgent.process(state, analysis, user_message)
          │    └─ LLMClient.complete(...) -> (reply_text, thoughts) (+ generation в Langfuse)
          ├─ InterviewSession adds thoughts to last turn
          ├─ InterviewSession creates next InterviewTurn with interviewer message
          └─ LangfuseTracker.add_span(name="interviewer_response")
```

Завершение:
- если `analysis.response_type == STOP_COMMAND` → интервью завершается сразу и вызывается `generate_feedback()`;
- если достигнут лимит `MAX_TURNS` → интервью завершается и формируется фидбэк.

---

## 4. «Активный технический вопрос» (якорь)

Система опирается на правило, что в интервью существует один активный вопрос — последнее сообщение интервьюера, ожидающее ответа кандидата.

Реализация:
- `InterviewSession` хранит `_last_agent_message`.
- `ObserverAgent` получает `last_question` и решает, ответил ли кандидат.
- `InterviewerAgent` получает в контексте «АКТИВНЫЙ ЯКОРЬ» и обязан возвращаться к нему при:
  - встречных вопросах,
  - off-topic,
  - галлюцинациях.

---

## 5. Адаптация сложности

Сущности:
- `DifficultyLevel` (BASIC/INTERMEDIATE/ADVANCED/EXPERT) — `src/app/schemas/interview.py`.
- `InterviewState.adjust_difficulty(analysis)`:
  - увеличивает сложность после серии хороших ответов,
  - уменьшает после серии плохих,
  - сбрасывает streak при отсутствии сигналов.

Сигналы:
- `ObserverAnalysis.should_increase_difficulty`
- `ObserverAnalysis.should_simplify`

---

## 6. Данные и модели (schemas)

### 6.1 Состояние интервью

Файл: `src/app/schemas/interview.py`

- `CandidateInfo`: имя, позиция, целевой грейд, опыт, технологии.
- `InterviewTurn`: один ход интервью (сообщение интервьюера, сообщение кандидата, мысли агентов).
- `InterviewState`: агрегирует историю ходов, навыки, пробелы, текущую сложность.

Ключевые поля `InterviewState`:
- `turns: list[InterviewTurn]`
- `current_difficulty: DifficultyLevel`
- `covered_topics: list[str]`
- `confirmed_skills: list[str]`
- `knowledge_gaps: list[dict[str, str]]`

---

### 6.2 Аналитика ObserverAgent

- `ObserverAnalysis`: тип ответа, качество, корректность, темы, рекомендация, correct_answer и extracted_info.

---

### 6.3 Финальный фидбэк

Файл: `src/app/schemas/feedback.py`

- `InterviewFeedback` содержит:
  - `verdict: Verdict`
  - `technical_review: TechnicalReview`
  - `soft_skills_review: SoftSkillsReview`
  - `roadmap: PersonalRoadmap`
  - `general_comments: str`

Метод `InterviewFeedback.to_formatted_string()` формирует человекочитаемый отчёт для UI и логов.

---

## 7. Форматы логов интервью

Файл: `src/app/interview/logger.py`

### 7.1 Основной лог (формат по ТЗ)
Имя файла: `interview_log_YYYYMMDD_HHMMSS.json`

Содержимое:
- `participant_name`
- `turns`: массив объектов `turn_id`, `agent_visible_message`, `user_message`, `internal_thoughts`
- `final_feedback`: строка (форматированный отчёт) или `null`

### 7.2 Детальный лог
Имя файла: `interview_detailed_YYYYMMDD_HHMMSS.json`

Содержимое:
- `participant_name`
- `candidate_info`: name/position/target_grade/experience/technologies
- `interview_stats`: total_turns, final_difficulty, confirmed_skills, knowledge_gaps, covered_topics
- `turns`: список ходов с `timestamp` и полным `internal_thoughts`
- `final_feedback`: `model_dump()` объекта `InterviewFeedback` или `null`
- `token_metrics` (добавляется после генерации фидбэка):
  - total токены, токены по агентам, количество ходов и генераций, средние значения.

---

## 8. LLM интеграция

Файл: `src/app/llm/client.py`

- Запросы идут в LiteLLM proxy: `POST /v1/chat/completions`.
- `LLMClient.complete(...)` — возвращает текстовый ответ.
- `LLMClient.complete_json(...)` — ожидает JSON-ответ и парсит его.

Параметры:
- `model` — из конфигурации или из параметра `create_interview_session(model)`.
- `temperature`, `max_tokens` — задаются на уровне вызовов агентов.
- `timeout`, `max_retries` — из `.env`.

---

## 8.1 Langfuse интеграция (observability)

### 8.1.1 Конфигурация

Файл: `src/app/core/config.py`

Переменные окружения:
- `LANGFUSE_ENABLED` — включить/выключить трекинг.
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` — ключи API.
- `LANGFUSE_HOST` — хост Langfuse:
  - в Docker Compose: `http://langfuse:3000`,
  - локально: обычно `http://localhost:3000`.

Особенность:
- если `LANGFUSE_ENABLED=true`, но ключи не заданы, трекинг отключается автоматически (логируется при инициализации).

### 8.1.2 Trace / Generation модель

- Trace создаётся на старте интервью-сессии и живёт до конца `generate_feedback()`.
- Generation создаётся на каждый LLM вызов (Observer / Interviewer / Evaluator) с именем `generation_name`
  (например `observer_analysis`, `interviewer_response`, `evaluator_feedback`).
- Usage (prompt_tokens / completion_tokens / total_tokens) берётся из ответа OpenAI-compatible API (`usage`)
  и сохраняется в `SessionMetrics`.

### 8.1.3 Метрики сессии

`SessionMetrics` агрегирует:
- `total_usage` и `by_agent` (observer/interviewer/evaluator),
- количество ходов (`turn_count`) и LLM вызовов (`generation_count`),
- средние значения.

Финализация:
- `LangfuseTracker.add_session_metrics_to_trace(...)` добавляет span с полной структурой метрик и score’ы.
- Метрики также сохраняются в детальный лог интервью (`token_metrics`).

---

## 9. Конфигурация приложения

Файл: `src/app/core/config.py`

- Используется `pydantic-settings`.
- Настройки сгруппированы в несколько классов:
  - `AppSettings`, `EnvironmentSettings`, `RedisCacheSettings`, `ClientSideCacheSettings`,
    `LogSettings`, `LiteLLMSettings`, `InterviewSettings`, `LangfuseSettings`.
- Все объединено в `Settings`, доступно как `settings = Settings()`.

Особенности:
- `APP_LOG_DIR` и `INTERVIEW_LOG_DIR` создаются при валидации.
- Есть вычисляемые поля `SYSTEM_LOG_PATH`, `PERSONAL_LOG_PATH`, `REDIS_CACHE_URL`.

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
- игнорирование prompt injection в блоках user input (описано в промптах Observer/Interviewer),
- сохранение активного вопроса при role reversal/off-topic/hallucination,
- фиксация чувствительных ключей в `SENSITIVE_KEYS` (модуль `src/app/core/constants.py`) для потенциального использования при редактировании логов запросов/ответов.

---

## 13. Точки расширения

### 13.1 Новые API endpoints
- Добавлять роутеры в `src/app/api/v1/` и подключать в `src/app/api/v1/__init__.py`.

### 13.2 Новые агенты
- Создать класс-наследник `BaseAgent`.
- Определить `system_prompt` и `process(...)`.
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
- Langfuse: наличие trace на сессию, generation на LLM вызовы, span’ы ключевых этапов.
- Логи приложения: наличие `system.log` и `personal.log` в `APP_LOG_DIR`.

---

## 15. Приложение: таблица ключевых файлов

| Назначение | Путь |
|---|---|
| UI (Gradio) | `src/app/ui/gradio_app.py` |
| Оркестрация интервью | `src/app/interview/session.py` |
| Логи интервью | `src/app/interview/logger.py` |
| Агенты | `src/app/agents/*` |
| LLM клиент | `src/app/llm/client.py` |
| Observability (Langfuse) | `src/app/observability/langfuse_client.py` |
| Конфигурация | `src/app/core/config.py` |
| Логирование | `src/app/core/logger_setup.py` |
| FastAPI setup | `src/app/core/setup.py` |
| Docker Compose | `docker-compose.yml` |
| Backend Dockerfile | `Dockerfile` |
| Gradio Dockerfile | `Dockerfile.gradio` |
