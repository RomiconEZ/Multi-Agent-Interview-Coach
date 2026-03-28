# Spec: Agent / Orchestrator — InterviewSession

Техническая спецификация оркестратора интервью и агентов.

---

## 1. Обзор

`InterviewSession` — центральный компонент системы, координирующий lifecycle интервью-сессии. Управляет последовательным вызовом агентов (Observer → Interviewer → Evaluator), обеспечивает атомарность мутаций `InterviewState` и интегрируется с Langfuse для observability.

**Файл**: `src/app/interview/session.py`

---

## 2. Шаги обработки сообщения (process_message)

| Stage | Название | Операция | Мутация state | Откатываема |
|---|---|---|---|---|
| 1 | **Observer** | `ObserverAgent.process(state, user_message, last_question)` | Нет | — |
| 2 | **Идемпотентное обновление** | `_update_candidate_info(extracted_info)` | `CandidateInfo` (только если поле = None) | Нет (идемпотентно) |
| 3 | **Стоп-команда** | Проверка `response_type == STOP_COMMAND` | `is_active = False` | Нет |
| 4 | **Корректировка сложности** | `state.adjust_difficulty(analysis)` + snapshot | `current_difficulty`, `consecutive_good/bad_answers` | Да (snapshot) |
| 5 | **Interviewer** | `InterviewerAgent.process(state, analysis, user_message)` | Нет | — |
| 6 | **Фиксация** | `_update_state_from_analysis()`, новый `InterviewTurn` | `covered_topics`, `confirmed_skills`, `knowledge_gaps`, `current_turn` | Нет (выполняется только при полном успехе) |

### Инвариант атомарности

Неидемпотентные мутации (Stage 6) применяются **только** при полном успехе Stage 1 и Stage 5. При сбое Interviewer (Stage 5) — откат Stage 4 к snapshot:

```python
saved_difficulty = state.current_difficulty
saved_good_streak = state.consecutive_good_answers
saved_bad_streak = state.consecutive_bad_answers

# ... Stage 5 fails ...

state.current_difficulty = saved_difficulty
state.consecutive_good_answers = saved_good_streak
state.consecutive_bad_answers = saved_bad_streak
```

---

## 3. Правила переходов

### 3.1 Переходы состояния сессии

```text
NOT_STARTED ──start()──→ ACTIVE ──STOP_COMMAND──→ FINISHING ──generate_feedback()──→ COMPLETED
                           │                                                           
                           ├──MAX_TURNS──→ FINISHING ──generate_feedback()──→ COMPLETED  
                           │                                                           
                           └──close()──→ CLOSED                                        
```

| Триггер | Условие | Действие |
|---|---|---|
| `STOP_COMMAND` | `analysis.response_type == ResponseType.STOP_COMMAND` | `is_active = False`, вызов `generate_feedback()` |
| `MAX_TURNS` | `current_turn >= config.max_turns` | `is_active = False`, вызов `generate_feedback()` |
| Кнопка «Завершить» | Пользователь нажал в UI | `is_active = False`, вызов `generate_feedback()` |
| Кнопка «Сбросить» | Пользователь нажал в UI | `close()`, создание новой сессии |

### 3.2 Переходы сложности (DifficultyLevel)

```text
BASIC ←→ INTERMEDIATE ←→ ADVANCED ←→ EXPERT
```

Переход происходит только при `answered_last_question = true` и streak ≥ 2:

| Сигнал | Действие | Условие перехода |
|---|---|---|
| `should_increase_difficulty = true` | `consecutive_good_answers += 1`, `consecutive_bad_answers = 0` | При streak ≥ 2: `difficulty += 1` |
| `should_simplify = true` | `consecutive_bad_answers += 1`, `consecutive_good_answers = 0` | При streak ≥ 2: `difficulty -= 1` |
| Оба `false` | `consecutive_good_answers = 0`, `consecutive_bad_answers = 0` | — |

**Инвариант**: если `answered_last_question = false` → оба флага принудительно `false` (детерминированная логика в `observer.py`).

---

## 4. Stop Conditions

| Условие | Источник | Поведение |
|---|---|---|
| `response_type == STOP_COMMAND` | Observer → analysis | Немедленное завершение, `generate_feedback()` |
| `current_turn >= max_turns` | InterviewSession | Завершение после последнего ответа Interviewer, `generate_feedback()` |
| Кнопка «Завершить» | Gradio UI | `stop_interview()` → `is_active = False` → `generate_feedback()` |
| `is_active == False` при входе | InterviewSession | `return "Интервью завершено.", True` |

---

## 5. Retry / Fallback

### 5.1 Retry по агентам

| Агент | `generation_retries` | Что retry'ится | Что НЕ retry'ится |
|---|---|---|---|
| **Observer** | 2 (default) | Ошибки парсинга JSON (`ValueError`, `KeyError`) | `LLMClientError` (пробрасывается немедленно) |
| **Interviewer** | 0 (default) | — (нет retry) | Все ошибки пробрасываются |
| **Evaluator** | 2 (default) | Ошибки парсинга JSON | `LLMClientError` (пробрасывается немедленно) |

### 5.2 Retry на уровне LLMClient

| Параметр | Default | Описание |
|---|---|---|
| `LITELLM_MAX_RETRIES` | 3 | Максимум повторных попыток HTTP-запроса |
| `LITELLM_RETRY_BACKOFF_BASE` | 0.5s | Базовая задержка exponential backoff |
| `LITELLM_RETRY_BACKOFF_MAX` | 30.0s | Максимальная задержка |
| Retryable HTTP codes | 429, 500, 502, 503, 504 | Коды, при которых выполняется retry |

### 5.3 Fallback-стратегии

| Компонент | Fallback |
|---|---|
| `complete_json()` | При HTTP 400 (response_format не поддерживается) → fallback на текстовый режим + JSON extraction. Кэшируется навсегда. |
| Observer сбой | `return ("Произошла техническая ошибка...", False)` — состояние НЕ мутируется |
| Interviewer сбой | Откат difficulty → `return ("Произошла техническая ошибка...", False)` |
| Evaluator сбой | Ошибка пробрасывается в UI |
| Health check fail | `raise LLMClientError("LLM API is not available...")` — сессия НЕ создаётся |

---

## 6. Агенты — спецификации

### 6.1 BaseAgent (абстрактный)

**Файл**: `src/app/agents/base.py`

| Метод | Описание |
|---|---|
| `system_prompt` (property, abstract) | Возвращает системный промпт агента |
| `_build_messages(user_content, history)` | Строит список сообщений с правильным чередованием ролей (system → [history] → user) |
| `_build_job_description_block(job_description)` | Формирует XML-блок `<job_description>` для контекста |
| `process(state, **kwargs)` (abstract) | Обрабатывает текущее состояние |

**Инвариант `_build_messages()`**: если `history` начинается с `assistant`, добавляется dummy `user: "Начнём интервью."`. Если `history` заканчивается на `user`, последний элемент удаляется (будет добавлен через `user_content`).

### 6.2 ObserverAgent

**Файл**: `src/app/agents/observer.py`

**Вход**: `state: InterviewState`, `user_message: str`, `last_question: str`

**Выход**: `ObserverAnalysis`

| Поле выхода | Тип | Описание |
|---|---|---|
| `response_type` | `ResponseType` | Классификация: NORMAL, HALLUCINATION, OFF_TOPIC, QUESTION, STOP_COMMAND, INTRODUCTION, INCOMPLETE, EXCELLENT |
| `quality` | `AnswerQuality` | EXCELLENT, GOOD, ACCEPTABLE, POOR, WRONG |
| `is_factually_correct` | `bool` | Фактическая корректность ответа |
| `is_gibberish` | `bool` | Бессмыслица / мусор |
| `answered_last_question` | `bool` | Ответил ли кандидат на активный вопрос (детерминированные override'ы) |
| `detected_topics` | `list[str]` | Обнаруженные темы |
| `recommendation` | `str` | Рекомендация для Interviewer с маркерами: ANSWERED=YES/NO, NEXT_STEP=ASK_NEW/REPEAT/FOLLOWUP, GIBBERISH_DETECTED=YES/NO |
| `should_simplify` | `bool` | Упростить сложность (принудительно false если answered=false) |
| `should_increase_difficulty` | `bool` | Усложнить (принудительно false если answered=false) |
| `correct_answer` | `str \| None` | Правильный ответ (только при галлюцинации) |
| `extracted_info` | `ExtractedCandidateInfo \| None` | Извлечённые данные кандидата (name, position, grade, experience, technologies) |
| `thoughts` | `list[InternalThought]` | Внутренние мысли агента |

**Детерминированные override'ы** (`_resolve_answered_last_question`):

1. `is_gibberish = true` → `answered = false` (безусловно).
2. LLM вернул явный `bool` → используется напрямую.
3. Fallback: `response_type ∈ UNANSWERED_RESPONSE_TYPES` → `false`, иначе `true`.

**Контекст для LLM**: candidate info + краткое резюме последних 5 ходов (100 символов/реплику) + last_question + user_message в `<user_input>`.

### 6.3 InterviewerAgent

**Файл**: `src/app/agents/interviewer.py`

**Вход**: `state: InterviewState`, `analysis: ObserverAnalysis`, `user_message: str`

**Выход**: `tuple[str, list[InternalThought]]` — (текст ответа, внутренние мысли)

**Ветвление по `_get_response_instruction()`**:

| Приоритет | Условие | Инструкция |
|---|---|---|
| 1 | `is_gibberish = true` | «Ошибка ввода» + переформулировать активный вопрос |
| 2 | `response_type = INTRODUCTION` | Поблагодарить + первый технический вопрос |
| 3 | `response_type = HALLUCINATION`, `answered = true` | Коррекция ошибки + новый вопрос |
| 4 | `response_type = HALLUCINATION`, `answered = false` | Коррекция ошибки + переформулировать активный вопрос |
| 5 | `response_type = OFF_TOPIC` | «Вернёмся к вопросам» + переформулировать |
| 6 | `response_type = QUESTION` | Краткий ответ + вернуться к активному вопросу |
| 7 | `response_type = INCOMPLETE`, `answered = true` | Попросить уточнить |
| 8 | `response_type = INCOMPLETE`, `answered = false` | Объяснить + переформулировать |
| 9 | Любой тип, `answered = false` | Переформулировать активный вопрос |
| 10 | `response_type = EXCELLENT` | Похвалить + следующий вопрос (усложнить) |
| 11 | `response_type = NORMAL` | Следующий технический вопрос |

**Контекст для LLM**: candidate info + state + активный якорь + user_message в `<user_input>` + analysis + instruction + полная история последних `HISTORY_WINDOW_TURNS` ходов.

### 6.4 EvaluatorAgent

**Файл**: `src/app/agents/evaluator.py`

**Вход**: `state: InterviewState`

**Выход**: `InterviewFeedback`

| Поле выхода | Тип | Описание |
|---|---|---|
| `verdict` | `Verdict` | grade (Intern–Lead), hiring_recommendation (Strong Hire/Hire/No Hire), confidence_score (0–100) |
| `technical_review` | `TechnicalReview` | confirmed_skills, knowledge_gaps (каждый с topic, is_confirmed, details, correct_answer) |
| `soft_skills_review` | `SoftSkillsReview` | clarity (Excellent–Poor), honesty, engagement |
| `roadmap` | `PersonalRoadmap` | items (topic, priority 1–5, reason, resources), summary |
| `general_comments` | `str` | Общие комментарии |

**Контекст для LLM**: candidate info + полная история всех ходов (с мыслями агентов) + skills summary + job_description.

**Guardrails в промпте**:
- Запрет галлюцинаций: каждое утверждение подкреплено репликой из диалога.
- Короткие интервью (< 3 ходов): низкий confidence_score (10–30), пустые списки.
- «Не знаю» — это отказ от ответа, не галлюцинация и не ошибка.

---

## 7. Активный якорь (Active Question Anchor)

**Механизм**: `InterviewSession._last_agent_message` хранит последнее сообщение интервьюера.

| Событие | Якорь | Interviewer |
|---|---|---|
| Кандидат ответил на вопрос | Закрыт → новый якорь | Задаёт новый вопрос |
| Кандидат сказал «не знаю» | Закрыт | Задаёт новый (более простой) вопрос |
| Кандидат ушёл в off-topic | Открыт | Переформулирует якорь |
| Кандидат задал встречный вопрос | Открыт | Кратко отвечает → переформулирует якорь |
| Кандидат отправил бессмыслицу | Открыт | «Ошибка ввода» → переформулирует якорь |
| Кандидат галлюцинировал по теме | Закрыт | Коррекция → новый вопрос |
| Кандидат галлюцинировал не по теме | Открыт | Коррекция → переформулирует якорь |

---

## 8. Метрики и наблюдаемость

### 8.1 Span'ы на каждый ход

| Span | Когда | Данные |
|---|---|---|
| `user_message` | При получении сообщения | input: user_message, metadata: turn number |
| `observer_analysis` | После Observer | output: response_type, quality, answered, recommendation |
| `candidate_info_update` | При извлечении данных | output: name, position, grade, technologies |
| `difficulty_change` | При изменении сложности | metadata: from, to |
| `interviewer_response` | После Interviewer | output: response_text, metadata: turn number |

### 8.2 Span'ы при завершении

| Span | Когда | Данные |
|---|---|---|
| `final_feedback` | После Evaluator | output: grade, hiring_recommendation, confidence_score |
| `session_token_metrics` | При финализации | output: полная структура SessionMetrics |

### 8.3 Score'ы на trace

| Score | Значение | Вес |
|---|---|---|
| `total_tokens` | Суммарные токены | 1.0 |
| `total_turns` | Количество ходов | 1.0 |
| `llm_calls` | Количество LLM-вызовов | 1.0 |
| `avg_tokens_per_turn` | Среднее токенов на ход | 1.0 |
| `confidence_score` | confidence_score / 100 | confidence_score / 100 |
| `session_cost_usd` | Суммарная стоимость | 1.0 |