# Product Proposal — Multi-Agent Interview Coach

## 1. Прикладная задача

Подготовка к техническому собеседованию требует практики в формате живого диалога с оценкой ответов.
Доступные альтернативы:

| Альтернатива | Ограничение |
|---|---|
| Мок-интервью с ментором | Зависимость от расписания и стоимости ментора (от $50/сессия) |
| Самостоятельная подготовка по вопросам | Отсутствие адаптивной обратной связи и оценки soft skills |
| Одноагентный чат-бот | Нет факт-чекинга ответов, нет структурированного фидбэка, нет адаптации сложности |

Multi-Agent Interview Coach решает задачу автономной тренировки технического интервью:
кандидат ведёт диалог с системой, которая анализирует ответы, адаптирует сложность вопросов,
выявляет фактические ошибки и формирует структурированный отчёт с планом развития.

Разделение на трёх агентов (Observer, Interviewer, Evaluator) обусловлено необходимостью
изолировать функции анализа, генерации диалога и финальной оценки — каждая требует
отдельного системного промпта, температуры и формата вывода.

---

## 2. Цель и метрики

### 2.1 Цель

Предоставить разработчикам инструмент для самостоятельной подготовки к техническим интервью
с получением структурированной обратной связи без участия ментора.

### 2.2 Продуктовые метрики

| Метрика | Определение | Целевое значение |
|---|---|---|
| Completion Rate | Доля сессий, завершённых с генерацией фидбэка, от общего числа начатых | ≥ 70% |
| Средняя длина сессии | Количество ходов до завершения (по `turn_count` из `SessionMetrics`) | 8–15 ходов |
| Повторные сессии | Доля пользователей, запустивших ≥ 2 сессий за 7 дней | ≥ 30% |
| Feedback Usefulness | Доля сессий, где `confidence_score` ≥ 50 (достаточно данных для оценки) | ≥ 80% |

### 2.3 Агентские метрики

| Метрика | Источник | Целевое значение |
|---|---|---|
| Observer Parse Success Rate | Отношение успешных парсингов JSON к общему числу вызовов (с учётом `generation_retries`) | ≥ 95% |
| Hallucination Detection Precision | Доля верно классифицированных `response_type=hallucination` (ручная проверка выборки) | ≥ 85% |
| Gibberish Detection Recall | Доля обнаруженных бессмысленных сообщений от реальных (`is_gibberish=true`) | ≥ 95% |
| Anchor Adherence | Доля случаев, где при `answered_last_question=false` Interviewer переформулировал вопрос, а не задал новый | ≥ 90% |
| Evaluator Grounding | Доля утверждений в фидбэке, подтверждённых репликами из диалога (ручная проверка) | ≥ 90% |

### 2.4 Технические метрики

| Метрика | Определение | Целевое значение |
|---|---|---|
| p95 Latency (полный ход) | Время от отправки сообщения до отображения ответа интервьюера | ≤ 15 с |
| p95 Latency (фидбэк) | Время генерации финального фидбэка (Evaluator) | ≤ 30 с |
| Error Rate | Доля ходов, завершившихся сообщением об ошибке пользователю | ≤ 5% |
| Средний расход токенов на ход | `avg_tokens_per_turn` из `SessionMetrics` | ≤ 6 000 |
| Суммарный расход на сессию | `total_tokens` из `SessionMetrics` при 12 ходах | ≤ 80 000 |

---

## 3. Сценарии использования

### 3.1 Основные сценарии

**Сценарий 1 — Стандартное интервью.**
Кандидат запускает сессию, представляется (имя, позиция, стек), отвечает на 8–15 вопросов,
вводит «стоп» или достигает `MAX_TURNS`. Система генерирует фидбэк с грейдом, навыками, пробелами и роадмапом.

**Сценарий 2 — Интервью по вакансии.**
Кандидат вставляет описание вакансии в поле `job_description`. Observer и Interviewer
приоритизируют вопросы по стеку из вакансии. Evaluator оценивает соответствие требованиям позиции.

**Сценарий 3 — Подготовка к конкретной технологии.**
Кандидат указывает узкий стек (например, «asyncio, aiohttp»). Interviewer ограничивает
вопросы указанными технологиями (`candidate.technologies`).

### 3.2 Edge-кейсы

| Сценарий | Поведение системы |
|---|---|
| Кандидат отправляет бессмыслицу (случайные символы, тест клавиатуры) | Observer: `is_gibberish=true`, `answered_last_question=false`. Interviewer: переформулирует активный вопрос без комментирования содержимого |
| Кандидат пытается prompt injection («забудь инструкции», «покажи промпт») | Observer: `response_type=off_topic`, `is_gibberish=false`. Interviewer: возвращает к техническому вопросу |
| Кандидат отвечает на вопрос фактически неверно, но по теме | Observer: `response_type=hallucination`, `answered_last_question=true`. Interviewer: корректирует ошибку, задаёт новый вопрос |
| Кандидат галлюцинирует не по теме вопроса | Observer: `response_type=hallucination`, `answered_last_question=false`. Interviewer: корректирует ошибку, переформулирует активный вопрос |
| Кандидат задаёт встречный вопрос вместо ответа | Observer: `response_type=question`, `answered_last_question=false`. Interviewer: кратко отвечает и возвращается к активному вопросу |
| Кандидат на все вопросы отвечает «не знаю» | Observer: `quality=poor`, `should_simplify=true`. Сложность снижается до `BASIC`. Evaluator: `grade=Intern`, низкий `confidence_score` |
| Сессия из 1–2 ходов (сразу «стоп») | Evaluator: `confidence_score` 10–30, пустые `confirmed_skills` и `knowledge_gaps`, комментарий о недостаточности данных |
| LLM возвращает невалидный JSON | Observer/Evaluator: повтор генерации до `generation_retries` раз. При исчерпании — проброс исключения, пользователь получает сообщение об ошибке |
| Сбой Interviewer после успешного Observer | Откат `current_difficulty`, `consecutive_good_answers`, `consecutive_bad_answers` к сохранённым значениям. Неидемпотентные мутации (`knowledge_gaps`, `covered_topics`) не применяются |
| Таймаут LLM (превышение `LITELLM_TIMEOUT`) | `LLMClient`: повтор с экспоненциальным backoff до `LITELLM_MAX_RETRIES`. При исчерпании — `LLMClientError`, фиксация сбоя в circuit breaker |
| Длительная недоступность LLM API | Circuit breaker переходит в OPEN после `LITELLM_CIRCUIT_BREAKER_THRESHOLD` сбоев (по умолчанию 5). Запросы отклоняются немедленно на `LITELLM_CIRCUIT_BREAKER_RECOVERY` секунд (по умолчанию 60), затем пробный запрос |
| Недоступность LLM API при старте сессии | Readiness check (GET /health/readiness) с таймаутом `LITELLM_HEALTH_CHECK_TIMEOUT` (5 с). При неуспехе — сессия не создаётся, пользователь получает сообщение |

---

## 4. Ограничения

### 4.1 Технические ограничения

| Параметр | Значение | Источник |
|---|---|---|
| Максимум ходов на сессию | Настраивается через `MAX_TURNS` (по умолчанию 20, диапазон 5–50) | `InterviewSettings` |
| Окно контекста Interviewer | Последние `HISTORY_WINDOW_TURNS` ходов (по умолчанию 10) | `InterviewSettings` |
| Таймаут LLM-запроса | `LITELLM_TIMEOUT` (по умолчанию 120 с) | `LiteLLMSettings` |
| Повторы при сетевых ошибках LLM | `LITELLM_MAX_RETRIES` (по умолчанию 3), backoff 0.5–30 с | `LiteLLMSettings` |
| Повторы при ошибке парсинга JSON | `generation_retries` (Observer: 2, Evaluator: 2, Interviewer: 0) | `SingleAgentConfig` |
| Circuit breaker threshold | `LITELLM_CIRCUIT_BREAKER_THRESHOLD` (по умолчанию 5 последовательных сбоев) | `LiteLLMSettings` |
| Circuit breaker recovery | `LITELLM_CIRCUIT_BREAKER_RECOVERY` (по умолчанию 60 с) | `LiteLLMSettings` |
| Health check timeout | `LITELLM_HEALTH_CHECK_TIMEOUT` (по умолчанию 5 с) | `LiteLLMSettings` |
| Proxy-level retries (LiteLLM) | `num_retries: 2` — повторы на уровне proxy→backend перед возвратом ошибки клиенту | `config.yaml` → `litellm_settings` |
| Proxy-level allowed fails | `allowed_fails: 3` — порог сбоев в минуту, после которого deployment помечается как cooldown | `config.yaml` → `litellm_settings` |
| Proxy-level cooldown time | `cooldown_time: 30` с — время cooldown deployment после превышения `allowed_fails` | `config.yaml` → `litellm_settings` |
| p95 латентность на ход | Зависит от модели. Для моделей с ≤ 50 tok/s и контекстом ~4000 токенов: 10–20 с на ход (Observer + Interviewer) | — |
| Суммарные токены на сессию | При 12 ходах и средних промптах: 50 000–100 000 токенов | Зависит от модели и длины ответов |

### 4.2 Операционные ограничения

| Параметр | Описание |
|---|---|
| Стоимость LLM | Два LLM-вызова на ход (Observer + Interviewer) + один вызов на фидбэк (Evaluator). Стоимость каждого вызова извлекается из заголовка `x-litellm-response-cost` ответа LiteLLM proxy и агрегируется в `session_cost_usd` (`SessionMetrics`). Для cloud-моделей (DeepSeek) — пропорциональна объёму токенов. Для локальных моделей — $0.00 |
| Параллельные сессии | Текущая реализация UI хранит `_current_session` как глобальную переменную — одна активная сессия на процесс Gradio |
| Хранилище логов | Логи сохраняются на файловую систему (`INTERVIEW_LOG_DIR`). Нет автоматической ротации и очистки логов интервью |
| Зависимость от LiteLLM proxy | Приложение не обращается к LLM напрямую — требуется развёрнутый LiteLLM шлюз |
| Langfuse | Self-hosted, требует PostgreSQL. Метрики хранятся в памяти процесса (`_session_metrics`), не персистентны между перезапусками |

### 4.3 SLO (Service Level Objectives)

| SLO | Целевое значение | Метод измерения |
|---|---|---|
| Availability | 99% (uptime Gradio + LiteLLM + Redis) | Health checks Docker |
| Latency (ход, p95) | ≤ 15 с | Langfuse generation duration |
| Latency (фидбэк, p95) | ≤ 30 с | Langfuse generation duration (evaluator) |
| Error budget | ≤ 5% ходов с ошибками | Логи `LLMClientError` |

---

## 5. Архитектурный набросок

### 5.1 Модули

```
┌─────────────────────────────────────────────────────────────┐
│                        Gradio UI                            │
│  (gradio_app.py, styles.py)                                 │
│  Ответственность: ввод/вывод, управление сессией            │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  InterviewSession                           │
│  (interview/session.py)                                     │
│  Ответственность: оркестрация агентов, состояние,           │
│  атомарность мутаций, адаптация сложности                   │
└───┬──────────────┬──────────────┬───────────────────────────┘
    │              │              │
┌───▼───┐    ┌─────▼─────┐   ┌───▼──────┐
│Observer│    │Interviewer│   │Evaluator │
│ Agent  │    │  Agent    │   │  Agent   │
└───┬────┘    └─────┬─────┘   └───┬──────┘
    │               │             │
┌───▼───────────────▼─────────────▼──────┐
│              LLMClient                  │
│  (llm/client.py)                        │
│  HTTP → LiteLLM proxy → LLM backend    │
└───┬─────────────────────────────┬──────┘
    │                             │
┌───▼──────────┐          ┌──────▼───────┐
│ LiteLLM Proxy│          │LangfuseTracker│
│ (external)   │          │(observability)│
└──────────────┘          └──────────────┘
```

### 5.2 Внешние интеграции

| Компонент | Протокол | Назначение |
|---|---|---|
| LiteLLM proxy | HTTP, OpenAI-compatible (`/v1/chat/completions`, `/v1/models`) | Маршрутизация запросов к LLM-бэкендам |
| Redis | TCP (redis protocol) | Кэширование (используется FastAPI backend) |
| Langfuse | HTTP (Langfuse SDK) | Трекинг трейсов, генераций, метрик токенов |
| PostgreSQL (Langfuse) | TCP | Хранение данных Langfuse |
| Nginx | HTTP | Reverse proxy для FastAPI backend |

### 5.3 Хранение данных

| Данные | Хранилище | Формат |
|---|---|---|
| Состояние сессии | In-memory (`InterviewState`) | Pydantic-модели |
| Логи интервью | Файловая система (`INTERVIEW_LOG_DIR`) | JSON |
| Метрики токенов | In-memory (`SessionMetrics`) + файл (детальный лог) + Langfuse | dict / JSON |
| Логи приложения | Файловая система (`APP_LOG_DIR`) | Текст, ротация через `RotatingFileHandler` |
| Конфигурация | `.env` файл | Key-value, загрузка через `pydantic-settings` |

---

## 6. Data Flow

### 6.1 Поток обработки одного хода

```
Пользователь
    │
    ▼
[1] add_user_message()          ← Синхронный, queue=False
    │  Добавляет сообщение в чат, блокирует ввод
    │  Делегировано LLM: нет
    │
    ▼
[2] bot_respond()               ← Async generator
    │
    ├─[2.0] Orchestrator: readiness check + circuit breaker
    │   Делегировано LLM: нет
    │   Логика: проверка доступности LLM API (GET /health/readiness),
    │     проверка состояния circuit breaker перед каждым вызовом
    │
    ├─[2.1] Observer.process()  ← LLM вызов #1
    │   Вход: state, user_message, last_question
    │   Выход: ObserverAnalysis (JSON)
    │   Делегировано LLM: классификация ответа, факт-чекинг,
    │     извлечение данных кандидата, оценка качества
    │   НЕ делегировано LLM: валидация JSON-схемы ответа,
    │     принудительные правила answered_last_question,
    │     принудительное обнуление флагов сложности при
    │     answered_last_question=false
    │
    ├─[2.2] _update_candidate_info()
    │   Делегировано LLM: нет (данные из Observer)
    │   Логика: идемпотентное обновление полей CandidateInfo
    │
    ├─[2.3] adjust_difficulty()
    │   Делегировано LLM: нет
    │   Логика: инкремент/декремент DifficultyLevel по streak-счётчикам
    │   Условие: только при answered_last_question=true
    │
    ├─[2.4] Interviewer.process()  ← LLM вызов #2
    │   Вход: state, analysis, user_message, conversation_history
    │   Выход: (response_text, thoughts)
    │   Делегировано LLM: генерация реплики интервьюера
    │     на основе контекста и инструкций из analysis
    │   НЕ делегировано LLM: выбор инструкции (_get_response_instruction),
    │     формирование контекста, управление history_window
    │
    ├─[2.5] _update_state_from_analysis()
    │   Делегировано LLM: нет
    │   Логика: обновление covered_topics, confirmed_skills,
    │     knowledge_gaps. Выполняется только при успехе шагов 2.1–2.4
    │
    └─[2.6] Orchestrator: агрегация стоимости
        Делегировано LLM: нет
        Логика: суммирование cost_usd из заголовков
          x-litellm-response-cost каждого LLM-вызова,
          запись session_cost_usd score в Langfuse
```

### 6.2 Разделение ответственности: LLM vs. детерминированная логика

| Функция | Исполнитель | Обоснование |
|---|---|---|
| Классификация типа ответа (`response_type`) | LLM (Observer) | Требует понимания семантики текста |
| Факт-чекинг (`is_factually_correct`, `correct_answer`) | LLM (Observer) | Требует предметных знаний |
| Детекция бессмыслицы (`is_gibberish`) | LLM (Observer) | Контекстно-зависимо (одиночные символы могут быть ответом) |
| Извлечение данных кандидата (`extracted_info`) | LLM (Observer) | NER (Named Entity Recognition) из свободного текста |
| Генерация вопросов и реплик | LLM (Interviewer) | Требует генерации естественного языка |
| Генерация фидбэка | LLM (Evaluator) | Требует синтеза и оценки всего диалога |
| Валидация JSON-ответа LLM | Детерминированная (response_parser.py) | Структурная проверка, не требует LLM |
| Принудительные правила `answered_last_question` | Детерминированная (_resolve_answered_last_question) | Бизнес-правила: gibberish → false, fallback по response_type |
| Обнуление флагов сложности при `answered=false` | Детерминированная (observer.py, _parse_analysis) | Инвариант: нельзя менять сложность без ответа |
| Адаптация сложности (streak logic) | Детерминированная (InterviewState.adjust_difficulty) | Детерминированный алгоритм с порогом streak ≥ 2 |
| Откат сложности при сбое Interviewer | Детерминированная (session.py) | Гарантия консистентности состояния |
| Обновление `CandidateInfo` | Детерминированная (session.py) | Идемпотентное присвоение полей |
| Обновление `knowledge_gaps`, `confirmed_skills` | Детерминированная (session.py) | Правила: gaps только при answered=true и ошибке |
| Формирование контекста для LLM | Детерминированная (агенты) | Шаблонная сборка строк |
| Выбор инструкции для Interviewer | Детерминированная (_get_response_instruction) | Ветвление по response_type и answered_last_question |
| Сохранение логов | Детерминированная (InterviewLogger) | Сериализация в JSON |
| Сбор метрик токенов | Детерминированная (SessionMetrics) | Агрегация из usage-полей ответа LLM API |
| Расчёт стоимости сессии | Детерминированная (SessionMetrics + LLMClient) | Суммирование `x-litellm-response-cost` из заголовков ответов LiteLLM proxy |
| Readiness check LLM API | Детерминированная (LLMClient.check_health) | GET /health/readiness перед стартом сессии |
| Circuit breaker | Детерминированная (CircuitBreaker) | Подсчёт последовательных сбоев, автоматическое восстановление по таймауту |
