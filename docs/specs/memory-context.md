# Spec: Memory / Context — Multi-Agent Interview Coach

Техническая спецификация управления состоянием сессии, политикой памяти и контекстным бюджетом.

---

## 1. Session State (InterviewState)

### 1.1 Модель данных

Файл: `src/app/schemas/interview.py`

| Поле | Тип | Мутабельность | Описание |
|---|---|---|---|
| `candidate` | `CandidateInfo` | Идемпотентная | Имя, позиция, грейд, опыт, технологии. Поле обновляется только если текущее значение `None`. |
| `job_description` | `str \| None` | Immutable после создания | Описание вакансии, задаётся при старте сессии. |
| `turns` | `list[InterviewTurn]` | Append-only (Stage 6) | Полная история ходов интервью. |
| `current_turn` | `int` | Increment (Stage 6) | Счётчик ходов, инкрементируется при `add_turn()`. |
| `current_difficulty` | `DifficultyLevel` | Stage 4 (с откатом) | BASIC / INTERMEDIATE / ADVANCED / EXPERT. |
| `covered_topics` | `list[str]` | Append (Stage 6) | Затронутые темы, идемпотентная проверка дубликатов. |
| `confirmed_skills` | `list[str]` | Append (Stage 6) | Подтверждённые навыки. Только при `answered=True` и `quality ∈ {EXCELLENT, GOOD}`. |
| `knowledge_gaps` | `list[dict[str, str \| None]]` | Append (Stage 6) | Пробелы. Только при `answered=True` и `is_factually_correct=False`. |
| `is_active` | `bool` | Write | Флаг активности сессии. |
| `consecutive_good_answers` | `int` | Stage 4 (с откатом) | Streak хороших ответов для адаптации сложности. |
| `consecutive_bad_answers` | `int` | Stage 4 (с откатом) | Streak плохих ответов для адаптации сложности. |

### 1.2 Вспомогательные модели

| Модель | Файл | Назначение |
|---|---|---|
| `CandidateInfo` | `schemas/interview.py` | Данные кандидата: name, position, target_grade, experience, technologies. |
| `InterviewTurn` | `schemas/interview.py` | Один ход: turn_id, agent_visible_message, user_message, internal_thoughts, timestamp. |
| `InternalThought` | `schemas/interview.py` | Мысль агента: from_agent, to_agent, content, timestamp. |
| `ObserverAnalysis` | `schemas/interview.py` | Результат анализа Observer'а. |
| `ExtractedCandidateInfo` | `schemas/interview.py` | Данные кандидата, извлечённые из текста (опциональные поля). |

### 1.3 Enums

| Enum | Значения | Файл |
|---|---|---|
| `ResponseType` | NORMAL, HALLUCINATION, OFF_TOPIC, QUESTION, STOP_COMMAND, INTRODUCTION, INCOMPLETE, EXCELLENT | `schemas/interview.py` |
| `AnswerQuality` | EXCELLENT, GOOD, ACCEPTABLE, POOR, WRONG | `schemas/interview.py` |
| `DifficultyLevel` | BASIC (1), INTERMEDIATE (2), ADVANCED (3), EXPERT (4) | `schemas/interview.py` |
| `GradeLevel` | INTERN, JUNIOR, MIDDLE, SENIOR, LEAD | `schemas/interview.py` |

### 1.4 Константы

| Константа | Тип | Значение | Назначение |
|---|---|---|---|
| `UNANSWERED_RESPONSE_TYPES` | `frozenset[ResponseType]` | `{OFF_TOPIC, QUESTION, STOP_COMMAND}` | Типы ответов, при которых кандидат не считается ответившим на вопрос. |

---

## 2. Memory Policy

### 2.1 Lifecycle состояния

```text
                     ┌────────────────────────────────────────┐
 create_interview    │                                        │
   _session()        │        InterviewState (in-memory)       │
        │            │                                        │
        ▼            │  Создаётся:   session.start()          │
  InterviewSession   │  Мутируется:  session.process_message()│
        │            │  Персистится: session.generate_feedback()│
        │            │  Теряется:    crash до generate_feedback│
        │            │                                        │
        │            └────────────────────────────────────────┘
        │                              │
        │                              ▼
        │            ┌────────────────────────────────────────┐
        │            │     JSON-логи (filesystem)             │
        │            │                                        │
        │            │  interview_log_*.json      — основной  │
        │            │  interview_detailed_*.json — детальный  │
        │            └────────────────────────────────────────┘
        │                              │
        │                              ▼
        │            ┌────────────────────────────────────────┐
        │            │     Langfuse (PostgreSQL)               │
        │            │                                        │
        │            │  Trace, Generations, Spans, Scores     │
        │            └────────────────────────────────────────┘
        ▼
  session.close()
  → clear_session_metrics()
  → flush Langfuse
  → close HTTP client
```

### 2.2 Short-term memory (сессия)

- **Scope**: один процесс, одна сессия.
- **Хранилище**: `InterviewState` как Pydantic `BaseModel` в памяти.
- **Доступ**: `InterviewSession._state`.
- **Разделение**: глобальная переменная `_current_session` в `gradio_app.py` — одна активная сессия на процесс.
- **При перезапуске**: состояние теряется полностью.

### 2.3 Long-term memory

- **Scope**: файловая система.
- **Формат**: JSON.
- **Ротация**: нет автоматической ротации логов интервью (каждая сессия — отдельный файл).
- **Очистка**: ответственность оператора (cron-задача для удаления старых файлов из `INTERVIEW_LOG_DIR`).

### 2.4 Cross-session memory

**Отсутствует**. Каждая сессия полностью независима. Нет профиля пользователя, нет аккумулирования данных между сессиями. Langfuse позволяет ретроспективный анализ сессий, но эти данные не используются в рантайме.

---

## 3. Context Budget (управление контекстным окном LLM)

### 3.1 Observer

| Компонент контекста | Источник | Размер (оценка) |
|---|---|---|
| Системный промпт | `OBSERVER_SYSTEM_PROMPT` | ~3 500 токенов (фиксированный) |
| Информация о кандидате | `CandidateInfo` | ~50–100 токенов |
| Описание вакансии | `job_description` (опц.) | 0–500 токенов |
| Резюме истории | `_summarize_history()` — 5 последних ходов × 100 символов/реплику | ~200–400 токенов |
| Последний вопрос интервьюера | `last_question` | ~50–100 токенов |
| Сообщение кандидата | `user_message` в `<user_input>` | ~20–500 токенов |
| Задача | Фиксированный блок | ~100 токенов |
| **Итого (вход)** | | **~4 000–5 200 токенов** |
| **max_tokens (выход)** | `config.observer.max_tokens` | **4 096 токенов** (default) |

**Стратегия ограничения**: обрезка истории до 5 ходов и 100 символов на реплику в `_summarize_history()`.

### 3.2 Interviewer

| Компонент контекста | Источник | Размер (оценка) |
|---|---|---|
| Системный промпт | `INTERVIEWER_SYSTEM_PROMPT` | ~2 500 токенов (фиксированный) |
| Информация о кандидате | `CandidateInfo` | ~50–100 токенов |
| Описание вакансии | `job_description` (опц.) | 0–500 токенов |
| Состояние (difficulty, skills, gaps) | Фиксированный блок | ~50–100 токенов |
| Активный якорь | `last_agent_message` | ~50–200 токенов |
| Сообщение кандидата | `user_message` в `<user_input>` | ~20–500 токенов |
| Анализ Observer | `ObserverAnalysis` fields | ~100–200 токенов |
| Инструкция | `_get_response_instruction()` | ~50–200 токенов |
| **История диалога** | `get_conversation_history(HISTORY_WINDOW_TURNS)` | **~1 000–4 000 токенов** |
| **Итого (вход)** | | **~4 000–8 300 токенов** |
| **max_tokens (выход)** | `config.interviewer.max_tokens` | **4 096 токенов** (default) |

**Стратегия ограничения**: `HISTORY_WINDOW_TURNS` (default: 10) — передаются только последние N ходов полностью. Более ранние ходы отбрасываются.

### 3.3 Evaluator

| Компонент контекста | Источник | Размер (оценка) |
|---|---|---|
| Системный промпт | `EVALUATOR_SYSTEM_PROMPT` | ~2 500 токенов (фиксированный) |
| Информация о кандидате | `CandidateInfo` | ~50–100 токенов |
| Описание вакансии | `job_description` (опц.) | 0–500 токенов |
| Статистика интервью | Фиксированный блок | ~30–50 токенов |
| **Полная история диалога** | Все ходы с мыслями | **~2 000–10 000 токенов** |
| Skills summary | confirmed_skills + knowledge_gaps + covered_topics | ~100–500 токенов |
| Инструкция и критерии | Фиксированный блок | ~200 токенов |
| **Итого (вход)** | | **~5 000–14 000 токенов** |
| **max_tokens (выход)** | `config.evaluator.max_tokens` | **4 096 токенов** (default) |

**Стратегия ограничения**: нет ограничения на историю (все ходы передаются). Ограничение — через `MAX_TURNS` (default: 20) и `max_tokens` на выход. При очень длинных сессиях (>20 ходов с развёрнутыми ответами) возможно исчерпание контекстного окна модели.

---

## 4. Атомарность мутаций состояния

### 4.1 Классификация мутаций

| Мутация | Stage | Тип | При сбое Interviewer |
|---|---|---|---|
| `CandidateInfo` update | 2 | Идемпотентная | Повторное обновление безопасно (поле → None guard) |
| `is_active = False` (stop) | 3 | Финализирующая | Не откатывается (стоп-команда финальна) |
| `current_difficulty` change | 4 | Откатываемая | **Откатывается** к `saved_difficulty` |
| `consecutive_good/bad_answers` | 4 | Откатываемая | **Откатывается** к saved values |
| `covered_topics` append | 6 | Неидемпотентная | **НЕ применяется** при сбое Interviewer |
| `confirmed_skills` append | 6 | Неидемпотентная | **НЕ применяется** при сбое Interviewer |
| `knowledge_gaps` append | 6 | Неидемпотентная | **НЕ применяется** при сбое Interviewer |
| `turns` append (новый ход) | 6 | Неидемпотентная | **НЕ применяется** при сбое Interviewer |
| `current_turn` increment | 6 | Неидемпотентная | **НЕ применяется** при сбое Interviewer |
| `_last_agent_message` update | 6 | Переписываемая | **НЕ применяется** при сбое Interviewer |

### 4.2 Snapshot и откат

```python
# Stage 4: Snapshot перед корректировкой
saved_difficulty = self._state.current_difficulty
saved_good_streak = self._state.consecutive_good_answers
saved_bad_streak = self._state.consecutive_bad_answers

# Stage 4: Корректировка (если answered)
if analysis.answered_last_question:
    self._state.adjust_difficulty(analysis)

# Stage 5: Interviewer
try:
    response, thoughts = await self._interviewer.process(...)
except (LLMClientError, Exception):
    # ROLLBACK
    self._state.current_difficulty = saved_difficulty
    self._state.consecutive_good_answers = saved_good_streak
    self._state.consecutive_bad_answers = saved_bad_streak
    return error_message, False

# Stage 6: Фиксация (только при полном успехе)
self._update_state_from_analysis(analysis, user_message)
```

### 4.3 Правила обновления state из analysis

Файл: `src/app/interview/session.py`, метод `_update_state_from_analysis()`.

- **covered_topics**: всегда пополняются из `analysis.detected_topics` (идемпотентно, с проверкой дубликатов).
- **confirmed_skills**: только при `answered_last_question=True` И `quality ∈ {EXCELLENT, GOOD}` И `is_factually_correct=True`.
- **knowledge_gaps**: только при `answered_last_question=True` И (`is_factually_correct=False` ИЛИ `quality=WRONG`).
- **Инвариант**: если `answered_last_question=False` → метод возвращается сразу после обновления `covered_topics`. Ни skills, ни gaps не обновляются, т.к. кандидат не демонстрировал знание/незнание.

---

## 5. Активный якорь (_last_agent_message)

### 5.1 Хранение

- Хранится в `InterviewSession._last_agent_message: str`.
- Обновляется в Stage 6 (`_last_agent_message = response`).
- Передаётся Observer'у как `last_question` и Interviewer'у в блоке «АКТИВНЫЙ ЯКОРЬ».

### 5.2 Семантика

- Observer определяет `answered_last_question` — ответил ли кандидат на этот конкретный вопрос.
- Interviewer обязан переформулировать якорь (та же тема, другая формулировка) при `answered=False`.
- Якорь считается закрытым (и обновляется) только в Stage 6 при полном успехе.

### 5.3 Определение answered_last_question

Функция `_resolve_answered_last_question()` (файл: `src/app/agents/observer.py`):

1. `is_gibberish=True` → **False** (бессмыслица → всегда не ответил).
2. LLM вернул explicit `bool` → используется напрямую.
3. Fallback: `response_type ∈ UNANSWERED_RESPONSE_TYPES` → **False**, иначе **True**.

---

## 6. Конфигурация

### 6.1 Настройки, влияющие на state/context

| Параметр | Default | Диапазон | Влияние |
|---|---|---|---|
| `MAX_TURNS` | 20 | 5–50 | Автоматическое завершение сессии при достижении |
| `HISTORY_WINDOW_TURNS` | 10 | ≥ 1 | Количество ходов в контексте Interviewer |
| `GREETING_MAX_TOKENS` | 300 | ≥ 1 | Максимум токенов для приветствия |
| `observer.temperature` | 0.3 | 0.0–2.0 | Температура Observer (низкая → детерминированный анализ) |
| `observer.max_tokens` | 4096 | 64–8192 | Максимум токенов на выход Observer |
| `observer.generation_retries` | 2 | 0–10 | Повторы при ошибке парсинга JSON |
| `interviewer.temperature` | 0.7 | 0.0–2.0 | Температура Interviewer (средняя → разнообразие вопросов) |
| `interviewer.max_tokens` | 4096 | 64–8192 | Максимум токенов на выход Interviewer |
| `interviewer.generation_retries` | 0 | 0–10 | Interviewer не использует retry (текстовый вывод) |
| `evaluator.temperature` | 0.3 | 0.0–2.0 | Температура Evaluator (низкая → структурированный фидбэк) |
| `evaluator.max_tokens` | 4096 | 64–8192 | Максимум токенов на выход Evaluator |
| `evaluator.generation_retries` | 2 | 0–10 | Повторы при ошибке парсинга JSON |

### 6.2 Модели конфигурации

| Модель | Файл | Назначение |
|---|---|---|
| `SingleAgentConfig` | `schemas/agent_settings.py` | temperature, max_tokens, generation_retries для одного агента |
| `AgentSettings` | `schemas/agent_settings.py` | Конфигурации для Observer, Interviewer, Evaluator |
| `InterviewConfig` | `schemas/agent_settings.py` | model, max_turns, job_description, agent_settings |

---

## 7. Ограничения и известные проблемы

| Ограничение | Описание | Mitigation |
|---|---|---|
| Потеря состояния при crash | `InterviewState` в памяти, нет WAL/checkpoint | Логи сохраняются только при `generate_feedback()` |
| Одна сессия на процесс | `_current_session` — глобальная переменная | Не предназначено для multi-user |
| Нет cross-session memory | Каждая сессия независима | Langfuse позволяет ретроспективный анализ |
| Рост контекста Evaluator | Передаётся полная история без ограничения | Ограничен `MAX_TURNS` (default: 20) |
| Нет автоматической ротации логов интервью | Каждая сессия — отдельный файл | Оператор настраивает cron |
| Идемпотентность CandidateInfo | Ошибочно извлечённое поле сохраняется навсегда | Нет механизма коррекции в рамках сессии |