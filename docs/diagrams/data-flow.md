# Data Flow Diagram — Multi-Agent Interview Coach

Диаграмма описывает, как данные проходят через систему, что хранится и что логируется.

---

## 1. Общий поток данных (один ход интервью)

```mermaid
flowchart LR
    subgraph INPUT["Входные данные"]
        UM["Сообщение кандидата<br/>(user_message: str)"]
        CFG["Конфигурация сессии<br/>(InterviewConfig)"]
    end

    subgraph STATE["In-Memory State"]
        IS["InterviewState<br/>• candidate<br/>• turns[]<br/>• difficulty<br/>• skills/gaps"]
        SM["SessionMetrics<br/>• total_usage<br/>• by_agent<br/>• cost_usd"]
        LAM["_last_agent_message<br/>(активный якорь)"]
    end

    subgraph PROCESSING["Обработка"]
        OBS["ObserverAgent<br/>→ ObserverAnalysis (JSON)"]
        UPD["Детерминированные<br/>обновления state"]
        INT["InterviewerAgent<br/>→ response_text (текст)"]
    end

    subgraph EXTERNAL["Внешние сервисы"]
        LLM["LiteLLM Proxy<br/>/v1/chat/completions"]
        LF["Langfuse<br/>(trace, generation, span)"]
    end

    subgraph OUTPUT["Выходные данные"]
        RESP["Ответ интервьюера<br/>(response: str)"]
        UI["Gradio UI<br/>(chatbot history)"]
    end

    UM --> OBS
    IS --> OBS
    LAM --> OBS
    OBS -->|"LLM call #1"| LLM
    LLM -->|"JSON response + usage"| OBS
    OBS -->|"ObserverAnalysis"| UPD
    OBS -->|"generation + span"| LF
    LLM -->|"usage, cost"| SM

    UPD -->|"candidate_info,<br/>difficulty"| IS
    UPD --> INT
    IS --> INT
    INT -->|"LLM call #2"| LLM
    LLM -->|"text response + usage"| INT
    INT -->|"generation + span"| LF
    LLM -->|"usage, cost"| SM

    INT -->|"response_text"| RESP
    INT -->|"thoughts, topics,<br/>skills, gaps"| IS
    INT -->|"response"| LAM
    RESP --> UI

    style INPUT fill:#1a3a5c,stroke:#4a9eff,color:#e2e8f0
    style STATE fill:#2d1a4e,stroke:#8b5cf6,color:#e2e8f0
    style PROCESSING fill:#1a3d2e,stroke:#10b981,color:#e2e8f0
    style EXTERNAL fill:#3d2e1a,stroke:#f59e0b,color:#e2e8f0
    style OUTPUT fill:#3d1a1a,stroke:#ef4444,color:#e2e8f0
```

---

## 2. Данные Observer (вход → выход)

```mermaid
flowchart TB
    subgraph IN["Вход Observer"]
        A1["InterviewState<br/>(candidate, turns, difficulty)"]
        A2["user_message: str"]
        A3["last_question: str<br/>(активный якорь)"]
    end

    subgraph CTX["Формирование контекста"]
        B1["_summarize_history()<br/>последние 5 ходов × 100 символов"]
        B2["_build_analysis_context()<br/>candidate info + history + question + user_input"]
        B3["_build_messages()<br/>system_prompt + context"]
    end

    subgraph LLM_CALL["LLM вызов"]
        C1["LLMClient.complete()<br/>temperature=0.3, max_tokens=4096"]
        C2["extract_json_from_llm_response()<br/>парсинг: &lt;r&gt; → &lt;result&gt; → code block → raw"]
    end

    subgraph OUT["Выход Observer"]
        D1["ObserverAnalysis"]
        D2["response_type: ResponseType"]
        D3["quality: AnswerQuality"]
        D4["is_gibberish: bool"]
        D5["answered_last_question: bool"]
        D6["extracted_info: ExtractedCandidateInfo | None"]
        D7["correct_answer: str | None"]
        D8["should_simplify / should_increase_difficulty"]
        D9["thoughts: list[InternalThought]"]
    end

    A1 --> B1
    A2 --> B2
    A3 --> B2
    B1 --> B2
    B2 --> B3
    B3 --> C1
    C1 --> C2
    C2 --> D1
    D1 --- D2
    D1 --- D3
    D1 --- D4
    D1 --- D5
    D1 --- D6
    D1 --- D7
    D1 --- D8
    D1 --- D9
```

---

## 3. Данные Interviewer (вход → выход)

```mermaid
flowchart TB
    subgraph IN["Вход Interviewer"]
        A1["InterviewState"]
        A2["ObserverAnalysis"]
        A3["user_message: str"]
    end

    subgraph CTX["Формирование контекста"]
        B1["_build_response_context()<br/>candidate + state + якорь +<br/>user_input в &lt;user_input&gt; + analysis"]
        B2["_get_response_instruction()<br/>ветвление по response_type"]
        B3["get_conversation_history(window=10)<br/>последние N ходов"]
        B4["_build_messages()<br/>system_prompt + history + context"]
    end

    subgraph LLM_CALL["LLM вызов"]
        C1["LLMClient.complete()<br/>temperature=0.7, max_tokens=4096"]
    end

    subgraph OUT["Выход Interviewer"]
        D1["response_text: str<br/>(естественный текст, без JSON)"]
        D2["thoughts: list[InternalThought]<br/>(от Observer + собственная мысль)"]
    end

    A1 --> B1
    A2 --> B1
    A2 --> B2
    A3 --> B1
    B2 --> B1
    A1 --> B3
    B1 --> B4
    B3 --> B4
    B4 --> C1
    C1 --> D1
    A2 --> D2
```

---

## 4. Данные Evaluator (вход → выход)

```mermaid
flowchart TB
    subgraph IN["Вход Evaluator"]
        A1["InterviewState<br/>(полная история, все ходы)"]
    end

    subgraph CTX["Формирование контекста"]
        B1["_build_evaluation_context()"]
        B2["_format_conversation()<br/>все ходы с мыслями"]
        B3["_format_skills_summary()<br/>confirmed_skills + knowledge_gaps"]
        B4["candidate_info + job_description"]
    end

    subgraph LLM_CALL["LLM вызов"]
        C1["LLMClient.complete()<br/>temperature=0.3, max_tokens=4096"]
        C2["extract_json_from_llm_response()"]
        C3["_parse_feedback()"]
    end

    subgraph OUT["Выход Evaluator"]
        D1["InterviewFeedback"]
        D2["verdict: Verdict<br/>(grade, hiring_rec, confidence)"]
        D3["technical_review: TechnicalReview<br/>(confirmed_skills, knowledge_gaps)"]
        D4["soft_skills_review: SoftSkillsReview<br/>(clarity, honesty, engagement)"]
        D5["roadmap: PersonalRoadmap<br/>(items, summary)"]
        D6["general_comments: str"]
    end

    A1 --> B1
    B1 --> B2
    B1 --> B3
    B1 --> B4
    B2 --> C1
    B3 --> C1
    B4 --> C1
    C1 --> C2
    C2 --> C3
    C3 --> D1
    D1 --- D2
    D1 --- D3
    D1 --- D4
    D1 --- D5
    D1 --- D6
```

---

## 5. Хранилища данных

```mermaid
flowchart TB
    subgraph RUNTIME["Runtime (in-memory)"]
        IS["InterviewState<br/>(Pydantic BaseModel)"]
        SM["SessionMetrics<br/>(dataclass)"]
        CB["CircuitBreaker<br/>(failure_count, state)"]
        SESS["_current_session<br/>(глобальная переменная)"]
    end

    subgraph FILESYSTEM["Файловая система"]
        SL["system.log<br/>(RotatingFileHandler, 10MB × 2)"]
        PL["personal.log<br/>(RotatingFileHandler, 10MB × 2)"]
        IL["interview_log_*.json<br/>(основной лог по ТЗ)"]
        DL["interview_detailed_*.json<br/>(детальный лог + token_metrics)"]
    end

    subgraph EXTERNAL_STORES["Внешние хранилища"]
        RD["Redis<br/>(FastAPI кэш)"]
        PG["PostgreSQL<br/>(Langfuse данные)"]
    end

    IS -->|"generate_feedback()"| IL
    IS -->|"generate_feedback()"| DL
    SM -->|"_save_metrics_to_log()"| DL

    IS -->|"span'ы, score'ы"| PG
    SM -->|"add_session_metrics_to_trace()"| PG

    SESS -->|"содержит"| IS
    SESS -->|"содержит"| SM

    style RUNTIME fill:#1a2744,stroke:#6366f1,color:#e2e8f0
    style FILESYSTEM fill:#2a1a1a,stroke:#ef4444,color:#e2e8f0
    style EXTERNAL_STORES fill:#1a2a1a,stroke:#10b981,color:#e2e8f0
```

---

## 6. Что хранится в каждом хранилище

### 6.1 In-Memory (InterviewState)

| Поле | Тип | Когда обновляется | Персистируется |
|---|---|---|---|
| `candidate` | `CandidateInfo` | Stage 2 (идемпотентно) | Да, в detailed log |
| `turns[]` | `list[InterviewTurn]` | Stage 6 (новый ход) | Да, в оба лога |
| `current_difficulty` | `DifficultyLevel` | Stage 4 (с откатом) | Да, в detailed log |
| `confirmed_skills` | `list[str]` | Stage 6 (при успехе) | Да, в detailed log |
| `knowledge_gaps` | `list[dict]` | Stage 6 (при успехе) | Да, в detailed log |
| `covered_topics` | `list[str]` | Stage 6 (при успехе) | Да, в detailed log |
| `consecutive_good/bad_answers` | `int` | Stage 4 (с откатом) | Нет |

### 6.2 Файловая система

| Файл | Формат | Содержимое | Создаётся |
|---|---|---|---|
| `interview_log_*.json` | JSON (`InterviewLog`) | turns (agent_message, user_message, thoughts string), final_feedback (formatted string) | `generate_feedback()` |
| `interview_detailed_*.json` | JSON (dict) | candidate_info, interview_stats, turns (с timestamps и thoughts dict), final_feedback (model_dump), token_metrics | `generate_feedback()` |
| `system.log` | Text | Системные события: LLM запросы, ошибки, изменения сложности, извлечение данных | Непрерывно, ротация |
| `personal.log` | Text | Запросы привязанные к request_id (FastAPI backend) | Непрерывно, ротация |

### 6.3 Langfuse (PostgreSQL)

| Сущность | Содержимое | Когда записывается |
|---|---|---|
| Trace | session_id, user_id (имя кандидата), metadata (model, max_turns) | `start()` |
| Generation | input messages, output, model, usage (tokens), cost_usd, name | Каждый `LLMClient.complete()` |
| Span | greeting, user_message, observer_analysis, interviewer_response, candidate_info_update, difficulty_change, final_feedback, session_token_metrics | По ходу `process_message()` и `generate_feedback()` |
| Score | total_tokens, total_turns, llm_calls, avg_tokens_per_turn, confidence_score, session_cost_usd | `generate_feedback()` |

---

## 7. Что логируется (сводка)

```mermaid
flowchart LR
    subgraph EVENTS["Ключевые события"]
        E1["LLM request attempt"]
        E2["LLM response received"]
        E3["Observer analysis result"]
        E4["Candidate info extracted"]
        E5["Difficulty changed"]
        E6["Interviewer failed → rollback"]
        E7["Feedback generated"]
        E8["Session metrics"]
        E9["Circuit breaker state change"]
        E10["Health check result"]
    end

    subgraph DESTINATIONS["Куда пишется"]
        SYS["system.log"]
        LFU["Langfuse"]
        DET["interview_detailed_*.json"]
        CON["Console (stdout)"]
    end

    E1 --> SYS
    E1 --> CON
    E2 --> SYS
    E2 --> CON
    E2 --> LFU
    E3 --> SYS
    E3 --> LFU
    E4 --> SYS
    E4 --> LFU
    E5 --> SYS
    E5 --> LFU
    E6 --> SYS
    E7 --> SYS
    E7 --> LFU
    E7 --> DET
    E8 --> SYS
    E8 --> LFU
    E8 --> DET
    E9 --> SYS
    E9 --> CON
    E10 --> SYS
```
