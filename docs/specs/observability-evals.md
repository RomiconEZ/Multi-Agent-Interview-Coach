# Spec: Observability / Evals — Multi-Agent Interview Coach

Техническая спецификация модуля observability и метрик качества системы.

---

## 1. Обзор

Модуль observability обеспечивает сквозной трекинг всех LLM-вызовов, этапов пайплайна и агрегацию метрик сессии. Реализован поверх self-hosted Langfuse (SDK) с graceful degradation при отключении.

**Файлы:**

| Файл | Роль |
|---|---|
| `src/app/observability/langfuse_client.py` | `LangfuseTracker` (singleton), `SessionMetrics`, `TokenUsage` |
| `src/app/observability/__init__.py` | Реэкспорт `get_langfuse_tracker`, `SessionMetrics` |
| `src/app/llm/client.py` | Создание generation на каждый LLM-вызов |
| `src/app/interview/session.py` | Создание trace, span'ов и score'ов |
| `src/app/core/config.py` | `LangfuseSettings` — конфигурация подключения |

---

## 2. Архитектура

```text
InterviewSession                    LLMClient
     │                                  │
     │ create_trace()                   │ create_generation()
     │ add_span()                       │ end_generation(usage, cost)
     │ score_trace()                    │ end_generation_with_error()
     │ add_session_metrics_to_trace()   │
     │ increment_turn()                 │
     │ flush()                          │
     ▼                                  ▼
┌──────────────────────────────────────────────┐
│           LangfuseTracker (Singleton)        │
│                                              │
│  ┌─────────────────────────────────────────┐ │
│  │  Langfuse SDK Client                    │ │
│  │  (async batch flush)                    │ │
│  └───────────────┬─────────────────────────┘ │
│                  │                            │
│  ┌───────────────▼─────────────────────────┐ │
│  │  _session_metrics: dict[str, Session-   │ │
│  │  Metrics]                                │ │
│  │  (in-memory, per session_id)             │ │
│  └─────────────────────────────────────────┘ │
└──────────────────────┬───────────────────────┘
                       │ HTTP (SDK)
                       ▼
              ┌─────────────────┐
              │ Langfuse Server  │
              │ (self-hosted)    │
              │ + PostgreSQL     │
              └─────────────────┘
```

---

## 3. Конфигурация

| Переменная | Тип | Default | Описание |
|---|---|---|---|
| `LANGFUSE_ENABLED` | `bool` | `true` | Включить/выключить Langfuse трекинг |
| `LANGFUSE_PUBLIC_KEY` | `str` | `""` | Публичный ключ Langfuse API |
| `LANGFUSE_SECRET_KEY` | `str` | `""` | Секретный ключ Langfuse API |
| `LANGFUSE_HOST` | `str` | `http://localhost:3000` | URL хоста Langfuse |

**Автоматическое отключение:** если `LANGFUSE_ENABLED=true`, но ключи не заданы (`PUBLIC_KEY` или `SECRET_KEY` пусты), трекинг отключается автоматически. Логируется при инициализации.

**Graceful degradation:** при `LANGFUSE_ENABLED=false` или отсутствии ключей все методы `LangfuseTracker` становятся no-op. Бизнес-логика не затрагивается: ни один вызов не выбрасывает исключение из-за отключённого Langfuse.

---

## 4. Компоненты

### 4.1 LangfuseTracker

**Паттерн:** Singleton через `get_langfuse_tracker()`.

**Ответственности:**

- Инициализация Langfuse SDK клиента.
- Создание и управление trace, generation, span, score.
- Хранение `_session_metrics: dict[str, SessionMetrics]` в памяти.
- Graceful shutdown (flush буферов при завершении приложения).

**Ключевые методы:**

| Метод | Вызывающий | Описание |
|---|---|---|
| `create_trace(name, session_id, metadata)` | `InterviewSession.start()` | Создаёт trace на сессию |
| `create_generation(trace, name, model, input_messages, metadata)` | `LLMClient.complete()` | Создаёт generation перед LLM-вызовом |
| `end_generation(generation, output, cost_usd, usage, session_id, generation_name)` | `LLMClient.complete()` | Завершает generation, обновляет `SessionMetrics` |
| `end_generation_with_error(generation, error)` | `LLMClient.complete()` | Завершает generation при ошибке |
| `add_span(trace, name, input_data, output_data, metadata)` | `InterviewSession` | Записывает span этапа пайплайна |
| `score_trace(trace, name, value, comment)` | `InterviewSession.generate_feedback()` | Добавляет числовой score к trace |
| `add_session_metrics_to_trace(trace, session_id)` | `InterviewSession.generate_feedback()` | Финализирует метрики: span + scores |
| `increment_turn(session_id)` | `InterviewSession.process_message()` | Увеличивает turn_count в metrics |
| `get_session_metrics(session_id)` | `InterviewSession` | Возвращает метрики или None |
| `clear_session_metrics(session_id)` | `InterviewSession.close()` | Очищает метрики при закрытии сессии |
| `flush()` | `InterviewSession.generate_feedback()` | Принудительный flush буферов SDK |
| `shutdown()` | `setup.py` lifespan shutdown | Корректное завершение SDK |

### 4.2 SessionMetrics

**Тип:** `dataclass`.

**Поля:**

| Поле | Тип | Описание |
|---|---|---|
| `total_usage` | `TokenUsage` | Суммарные токены по всем агентам |
| `observer_usage` | `TokenUsage` | Токены Observer |
| `interviewer_usage` | `TokenUsage` | Токены Interviewer |
| `evaluator_usage` | `TokenUsage` | Токены Evaluator |
| `observer_calls` | `int` | Количество вызовов Observer |
| `interviewer_calls` | `int` | Количество вызовов Interviewer |
| `evaluator_calls` | `int` | Количество вызовов Evaluator |
| `generation_count` | `int` | Общее количество LLM-вызовов |
| `turn_count` | `int` | Количество ходов интервью |

**Вычисляемые методы:**

| Метод | Формула |
|---|---|
| `get_average_tokens_per_turn()` | `total_usage.total_tokens / turn_count` |
| `get_average_tokens_per_generation()` | `total_usage.total_tokens / generation_count` |
| `get_total_cost()` | `total_usage.cost_usd` |
| `get_cost_per_turn()` | `total_usage.cost_usd / turn_count` |
| `to_dict()` | Полный словарь для JSON-лога |
| `to_summary_string()` | Человекочитаемый отчёт для UI |

**Маршрутизация по `generation_name`:**

| Prefix в generation_name | Целевой агент |
|---|---|
| `observer_*` | `observer_usage`, `observer_calls` |
| `interviewer_*` | `interviewer_usage`, `interviewer_calls` |
| `evaluator_*` | `evaluator_usage`, `evaluator_calls` |

### 4.3 TokenUsage

**Тип:** `dataclass`.

**Поля:** `input_tokens: int`, `output_tokens: int`, `total_tokens: int`, `cost_usd: float`.

**Метод `add()`:** Аккумулирует значения. Вызывается из `SessionMetrics.add_generation()`.

---

## 5. Трейсы и span'ы

### 5.1 Структура trace

Один trace на сессию интервью:

```text
Trace: interview_session
  ├── session_id: str (UUID)
  ├── user_id: str (имя кандидата, если извлечено)
  ├── metadata: {model, max_turns, has_job_description}
  │
  ├── Span: greeting
  │     └── output: greeting_text
  │
  ├── [Per turn:]
  │   ├── Span: user_message
  │   │     ├── input: user_message
  │   │     └── metadata: {turn: N}
  │   │
  │   ├── Generation: observer_analysis
  │   │     ├── input: messages
  │   │     ├── output: content
  │   │     ├── usage: {input, output, total}
  │   │     └── cost_usd: float
  │   │
  │   ├── Span: observer_analysis
  │   │     └── output: {response_type, quality, answered, recommendation}
  │   │
  │   ├── Span: candidate_info_update (опционально)
  │   │     └── output: {name, position, grade, technologies}
  │   │
  │   ├── Span: difficulty_change (опционально)
  │   │     └── metadata: {from, to}
  │   │
  │   ├── Generation: interviewer_response
  │   │     ├── input: messages
  │   │     ├── output: content
  │   │     ├── usage: {input, output, total}
  │   │     └── cost_usd: float
  │   │
  │   └── Span: interviewer_response
  │         ├── output: response_text
  │         └── metadata: {turn: N}
  │
  ├── Generation: evaluator_feedback
  │     ├── input: messages
  │     ├── output: content
  │     ├── usage: {input, output, total}
  │     └── cost_usd: float
  │
  ├── Span: final_feedback
  │     └── output: {grade, hiring_recommendation, confidence_score}
  │
  ├── Span: session_token_metrics
  │     └── output: SessionMetrics.to_dict()
  │
  └── Scores:
        ├── total_tokens: int
        ├── total_turns: int
        ├── llm_calls: int
        ├── avg_tokens_per_turn: float
        ├── confidence_score: float (weight = value/100)
        └── session_cost_usd: float
```

### 5.2 Lifecycle trace

| Событие | Когда | Метод |
|---|---|---|
| Создание | `InterviewSession.start()` | `create_trace()` |
| Обновление user_id | При извлечении имени кандидата | `trace.update(user_id=name)` |
| Финализация | `InterviewSession.generate_feedback()` | `add_session_metrics_to_trace()`, `score_trace()`, `flush()` |

---

## 6. Метрики

### 6.1 Продуктовые метрики

| Метрика | Определение | Целевое значение | Источник |
|---|---|---|---|
| Completion Rate | Доля сессий с фидбэком от общего числа начатых | ≥ 70% | `SessionMetrics` (наличие evaluator_calls > 0) |
| Средняя длина сессии | `turn_count` из SessionMetrics | 8–15 ходов | `SessionMetrics.turn_count` |
| Feedback Usefulness | Доля сессий с `confidence_score ≥ 50` | ≥ 80% | Langfuse score `confidence_score` |

### 6.2 Агентские метрики

| Метрика | Определение | Целевое значение | Источник |
|---|---|---|---|
| Observer Parse Success Rate | Успешные парсинги JSON / общее число вызовов (с retry) | ≥ 95% | Логи: warnings `Observer generation parsing failed` vs. total calls |
| Hallucination Detection Precision | Верно классифицированные `hallucination` / все `hallucination` | ≥ 85% | Ручная проверка выборки span'ов `observer_analysis` |
| Gibberish Detection Recall | Обнаруженные бессмысленные / реальные бессмысленные | ≥ 95% | Ручная проверка span'ов с `is_gibberish=true` |
| Anchor Adherence | При `answered=false` Interviewer переформулировал вопрос / не задал новый | ≥ 90% | Ручная проверка span'ов `interviewer_response` |
| Evaluator Grounding | Утверждения в фидбэке, подтверждённые репликами из диалога | ≥ 90% | Ручная проверка span'ов `final_feedback` |

### 6.3 Технические метрики

| Метрика | Определение | Целевое значение | Источник |
|---|---|---|---|
| p95 Latency (ход) | Время от отправки сообщения до ответа | ≤ 15s | Langfuse generation duration (observer + interviewer) |
| p95 Latency (фидбэк) | Время генерации фидбэка | ≤ 30s | Langfuse generation duration (evaluator) |
| Error Rate | Ходы с ошибкой / общее число ходов | ≤ 5% | Логи `LLMClientError`, Langfuse `end_generation_with_error` |
| Avg tokens per turn | `avg_tokens_per_turn` из SessionMetrics | ≤ 6 000 | Langfuse score `avg_tokens_per_turn` |
| Total tokens per session (12 turns) | `total_tokens` из SessionMetrics | ≤ 80 000 | Langfuse score `total_tokens` |
| Circuit breaker activations | Переходы в OPEN state | Минимально | Логи: `Circuit breaker OPENED` |
| Session cost | `session_cost_usd` | Зависит от модели | Langfuse score `session_cost_usd` |

---

## 7. Логирование

### 7.1 Уровни и фильтры

| Категория | Файл | Фильтр | Содержимое |
|---|---|---|---|
| Системные | `system.log` | `log_type=SYSTEM` | LLM-запросы, ошибки, difficulty changes, candidate info extraction |
| Персональные | `personal.log` | `log_type=PERSONAL` | Записи привязанные к `request_id` (FastAPI) |
| Консоль | stdout | Все `log_type` | Дублирование системных + внешних (`EXTERNAL`) |

### 7.2 Ротация

| Параметр | Значение | Настройка |
|---|---|---|
| Максимальный размер файла | 10 MB (`LOG_MAX_BYTES`) | `.env` |
| Количество backup | 2 (`LOG_BACKUP_COUNT`) | `.env` |
| Механизм | `RotatingFileHandler` (stdlib) | — |
| Форматирование времени | `%Y-%m-%d %H:%M:%S`, TZ из `APP_TZ_OFFSET` | — |

### 7.3 Ключевые логируемые события

| Событие | Уровень | Формат |
|---|---|---|
| LLM request attempt | DEBUG | `LLM request attempt {N}/{max}, model={model}, json_mode={bool}` |
| LLM response received | DEBUG | `LLM response received, length={len}, usage={dict}, cost=${float}` |
| HTTP error on attempt | WARNING | `HTTP error on attempt {N}: status={code}, body={text}` |
| Timeout on attempt | WARNING | `Timeout on attempt {N}/{max}` |
| Circuit breaker OPENED | WARNING | `Circuit breaker OPENED after {N} consecutive failures (threshold={T})` |
| Circuit breaker reset | INFO | `Circuit breaker reset to CLOSED from {state}` |
| Observer parse failed | WARNING | `Observer generation parsing failed (attempt {N}/{max}): {error}` |
| Observer analysis | DEBUG | `Observer analysis: type={type}, quality={quality}, answered={bool}` |
| Difficulty changed | INFO | `ADAPTIVITY: Difficulty changed from {old} to {new} (good_streak: ..., bad_streak: ...)` |
| Candidate info extracted | INFO | `Extracted candidate name: {name}` / `Extracted technologies: [...]` |
| Interviewer failed + rollback | ERROR | `Interviewer failed: {error}` (+ rollback logged implicitly) |
| Feedback generated | INFO | `Generating final feedback` + `SessionMetrics.to_summary_string()` |
| Token metrics saved | INFO | `Token metrics added to log: {path}, cost=${float}` |
| Health check result | INFO/WARNING | `LLM API readiness check passed/failed/timed out` |

---

## 8. Логи интервью

### 8.1 Основной лог (формат по ТЗ)

**Файл:** `interview_log_YYYYMMDD_HHMMSS.json`

**Модель:** `InterviewLog`

```json
{
  "turns": [
    {
      "turn_id": 1,
      "agent_visible_message": "Приветствие...",
      "user_message": "Ответ кандидата...",
      "internal_thoughts": "[Observer_Agent]: анализ...\n[Interviewer_Agent]: мысли...\n"
    }
  ],
  "final_feedback": "============== ФИНАЛЬНЫЙ ФИДБЭК ==============\n..."
}
```

### 8.2 Детальный лог

**Файл:** `interview_detailed_YYYYMMDD_HHMMSS.json`

```json
{
  "candidate_info": {
    "name": "Иван",
    "position": "Backend Developer",
    "target_grade": "Middle",
    "experience": "3 года",
    "technologies": ["Python", "FastAPI", "PostgreSQL"]
  },
  "interview_stats": {
    "total_turns": 10,
    "final_difficulty": "INTERMEDIATE",
    "confirmed_skills": ["Python basics", "HTTP"],
    "knowledge_gaps": [{"topic": "GIL", "correct_answer": "..."}],
    "covered_topics": ["Python", "HTTP", "REST"]
  },
  "turns": [
    {
      "turn_id": 1,
      "agent_visible_message": "...",
      "user_message": "...",
      "internal_thoughts": [
        {"from": "Observer", "to": "Interviewer", "content": "..."}
      ],
      "timestamp": "2025-01-15T14:30:00"
    }
  ],
  "final_feedback": { "verdict": {...}, "technical_review": {...}, ... },
  "token_metrics": {
    "total": {"input_tokens": 45000, "output_tokens": 12000, "total_tokens": 57000, "cost_usd": 0.0057},
    "by_agent": {
      "observer": {"input_tokens": 20000, "output_tokens": 5000, ...},
      "interviewer": {"input_tokens": 18000, "output_tokens": 4000, ...},
      "evaluator": {"input_tokens": 7000, "output_tokens": 3000, ...}
    },
    "turn_count": 10,
    "generation_count": 21,
    "avg_tokens_per_turn": 5700,
    "avg_tokens_per_generation": 2714,
    "total_cost_usd": 0.0057,
    "cost_per_turn_usd": 0.00057
  }
}
```

---

## 9. Scores в Langfuse

Scores добавляются к trace при финализации (`generate_feedback()`):

| Score name | Тип | Источник | Описание |
|---|---|---|---|
| `total_tokens` | Numeric | `SessionMetrics.total_usage.total_tokens` | Суммарные токены за сессию |
| `total_turns` | Numeric | `SessionMetrics.turn_count` | Количество ходов |
| `llm_calls` | Numeric | `SessionMetrics.generation_count` | Количество LLM-вызовов |
| `avg_tokens_per_turn` | Numeric | `SessionMetrics.get_average_tokens_per_turn()` | Среднее токенов на ход |
| `confidence_score` | Numeric (0–1) | `InterviewFeedback.verdict.confidence_score / 100` | Уверенность в оценке (weight) |
| `session_cost_usd` | Numeric | `SessionMetrics.get_total_cost()` | Стоимость сессии в USD |

---

## 10. Evals — подход к оценке качества

### 10.1 Автоматические проверки (runtime)

| Проверка | Где | Как |
|---|---|---|
| JSON парсинг Observer/Evaluator | `response_parser.py` | Четыре стратегии извлечения, retry при неудаче |
| Schema validation | `observer.py`, `evaluator.py` | Pydantic модели (`ObserverAnalysis`, `InterviewFeedback`) |
| Детерминированные инварианты | `observer.py` | `answered_last_question` override: gibberish → false; difficulty flags → false if not answered |
| Confidence score bounds | `evaluator.py` | `min(100, max(0, ...))` |

### 10.2 Offline evals (рекомендуемые)

| Eval | Метод | Данные | Частота |
|---|---|---|---|
| Hallucination Detection Precision | Ручная разметка выборки из Langfuse span'ов `observer_analysis` с `response_type=hallucination` | 50–100 samples | Ежемесячно или при смене модели |
| Evaluator Grounding | Проверка каждого утверждения в `final_feedback` на наличие подтверждающей реплики в диалоге | 20–50 sessions | Ежемесячно или при смене модели |
| Anchor Adherence | Проверка: при `answered=false` Interviewer переформулировал вопрос, а не задал новый | 50–100 turns | Ежемесячно |
| Gibberish Detection | Отправка известных gibberish-сообщений, проверка `is_gibberish=true` | Regression set | При обновлении промпта Observer |
| Prompt Injection Resistance | Отправка injection-атак, проверка `response_type=off_topic` | Security test set (llamator) | При обновлении промптов |

### 10.3 Инструменты

- **Langfuse UI**: Просмотр trace, генераций, scores. Фильтрация по session_id, user_id, score ranges.
- **llamator** (`security-tests-llamator/`): Jupyter notebook для тестирования устойчивости к prompt injection.
- **Детальные логи**: JSON-файлы для offline-анализа без зависимости от Langfuse.

---

## 11. Ограничения

| Ограничение | Описание | Mitigation |
|---|---|---|
| Метрики в памяти | `_session_metrics` хранятся в памяти процесса, не персистентны между перезапусками | Метрики сохраняются в детальный лог и Langfuse при `generate_feedback()` |
| Нет автоматических evals | Нет pipeline для автоматического запуска offline evals | Рекомендуется настроить cron или CI/CD для периодических проверок |
| Нет alerting | Нет интеграции с системами оповещения (PagerDuty, Slack) | Мониторинг через Langfuse UI и логи |
| Single-session metrics | Метрики агрегируются только в рамках одной сессии, нет cross-session аналитики | Langfuse UI предоставляет агрегацию по sessions |
| Cost tracking зависит от LiteLLM | Стоимость извлекается из заголовка `x-litellm-response-cost`. Для моделей без настроенного прайсинга — $0.00 | Настроить прайсинг в LiteLLM `config.yaml` |