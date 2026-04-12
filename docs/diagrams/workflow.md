# Workflow Diagrams — Multi-Agent Interview Coach

Диаграммы описывают пошаговое выполнение запроса, включая ветки ошибок и финализацию.

---

## 1. Workflow обработки одного хода (Message Processing)

```mermaid
flowchart TD
    A([Пользователь отправляет сообщение]) --> B["add_user_message()<br/><i>sync, queue=False</i>"]
    B --> B1[Добавить сообщение в чат UI]
    B1 --> B2[Заблокировать ввод]
    B2 --> C["bot_respond()<br/><i>async generator</i>"]

    C --> D["InterviewSession.process_message()"]

    D --> E["Записать user_message<br/>в последний InterviewTurn"]
    E --> F["LangfuseTracker.add_span<br/>name=user_message"]

    F --> G{{"Stage 1: Observer"}}
    G --> G1["ObserverAgent.process()<br/>→ LLMClient.complete()<br/>→ LLM Call #1"]
    G1 --> G2{Успех?}
    G2 -->|Нет| G3["return error message<br/><b>NO state mutation</b>"]
    G3 --> Z1([Разблокировать ввод])

    G2 -->|Да| H["ObserverAnalysis:<br/>response_type, quality,<br/>answered_last_question,<br/>is_gibberish, extracted_info"]
    H --> H1["LangfuseTracker.add_span<br/>name=observer_analysis"]

    H1 --> I{{"Stage 2: Идемпотентное<br/>обновление CandidateInfo"}}
    I --> I1{extracted_info<br/>не пуст?}
    I1 -->|Да| I2["_update_candidate_info()<br/><i>поле обновляется только<br/>если текущее = None</i>"]
    I1 -->|Нет| J
    I2 --> J

    J --> K{{"Stage 3: Стоп-команда?"}}
    K --> K1{response_type ==<br/>STOP_COMMAND?}
    K1 -->|Да| K2["is_active = False"]
    K2 --> K3(["→ generate_feedback()"])

    K1 -->|Нет| L{{"Stage 4: Корректировка<br/>сложности"}}
    L --> L0["Snapshot:<br/>saved_difficulty<br/>saved_good_streak<br/>saved_bad_streak"]
    L0 --> L1{answered_last_question?}
    L1 -->|Да| L2["state.adjust_difficulty(analysis)<br/><i>streak ≥ 2 → difficulty ±1</i>"]
    L1 -->|Нет| L3["Skip<br/><i>нельзя менять сложность<br/>без ответа на вопрос</i>"]
    L2 --> M
    L3 --> M

    M --> N{{"Stage 5: Interviewer"}}
    N --> N1["InterviewerAgent.process()<br/>→ LLMClient.complete()<br/>→ LLM Call #2"]
    N1 --> N2{Успех?}
    N2 -->|Нет| N3["ROLLBACK:<br/>difficulty = saved<br/>good_streak = saved<br/>bad_streak = saved"]
    N3 --> N4["return error message<br/><b>NO non-idempotent mutations</b>"]
    N4 --> Z1

    N2 -->|Да| O{{"Stage 6: Фиксация"}}
    O --> O1["increment_turn()"]
    O1 --> O2["_update_state_from_analysis()<br/>→ covered_topics<br/>→ confirmed_skills<br/>→ knowledge_gaps"]
    O2 --> O3["_last_agent_message = response"]
    O3 --> O4["Записать thoughts<br/>в последний turn"]
    O4 --> O5["Создать новый InterviewTurn<br/>с ответом Interviewer"]
    O5 --> O6["LangfuseTracker.add_span<br/>name=interviewer_response"]

    O6 --> P{current_turn ≥<br/>MAX_TURNS?}
    P -->|Да| P1["is_active = False"]
    P1 --> P2(["→ generate_feedback()"])
    P -->|Нет| Q(["yield response<br/>Разблокировать ввод"])

    style G fill:#4a5568,stroke:#a0aec0,color:#fff
    style I fill:#4a5568,stroke:#a0aec0,color:#fff
    style K fill:#4a5568,stroke:#a0aec0,color:#fff
    style L fill:#4a5568,stroke:#a0aec0,color:#fff
    style N fill:#4a5568,stroke:#a0aec0,color:#fff
    style O fill:#4a5568,stroke:#a0aec0,color:#fff
    style G3 fill:#e53e3e,stroke:#c53030,color:#fff
    style N3 fill:#e53e3e,stroke:#c53030,color:#fff
    style N4 fill:#e53e3e,stroke:#c53030,color:#fff
    style K2 fill:#38a169,stroke:#276749,color:#fff
    style P1 fill:#38a169,stroke:#276749,color:#fff
```

---

## 2. Workflow генерации фидбэка (Feedback Generation)

```mermaid
flowchart TD
    START([Trigger:<br/>STOP_COMMAND /<br/>MAX_TURNS /<br/>кнопка Завершить]) --> A["InterviewSession.generate_feedback()"]

    A --> B["EvaluatorAgent.process(state)"]
    B --> B1["_build_evaluation_context():<br/>candidate_info + conversation +<br/>skills_summary + job_description"]
    B1 --> B2["LLMClient.complete()<br/>generation_name=evaluator_feedback"]
    B2 --> B3{JSON парсинг<br/>успешен?}
    B3 -->|Нет| B4{"attempt &lt;<br/>generation_retries?"}
    B4 -->|Да| B2
    B4 -->|Нет| B5[/"raise ValueError<br/>или LLMClientError"/]
    B5 --> ERR([Ошибка → UI])

    B3 -->|Да| C["_parse_feedback() →<br/>InterviewFeedback"]
    C --> D["LangfuseTracker.add_span<br/>name=final_feedback"]
    D --> E["LangfuseTracker.score_trace<br/>confidence_score"]
    E --> F["LangfuseTracker<br/>.add_session_metrics_to_trace()"]
    F --> G["LangfuseTracker.flush()"]
    G --> H["InterviewLogger.save_session()<br/>→ interview_log_*.json"]
    H --> I["InterviewLogger.save_raw_log()<br/>→ interview_detailed_*.json"]
    I --> J["_save_metrics_to_log()<br/>→ token_metrics в детальный лог"]
    J --> K(["return (feedback,<br/>summary_path,<br/>detailed_path)"])

    style B5 fill:#e53e3e,stroke:#c53030,color:#fff
    style ERR fill:#e53e3e,stroke:#c53030,color:#fff
    style K fill:#38a169,stroke:#276749,color:#fff
```

---

## 3. Workflow старта сессии (Session Start)

```mermaid
flowchart TD
    A([Пользователь нажимает<br/>Начать интервью]) --> B["start_interview()"]
    B --> B0["Закрыть предыдущую<br/>сессию если есть"]
    B0 --> C["create_interview_session(config)"]
    C --> C1["create_llm_client(model)"]
    C1 --> C2["create_interview_logger()"]
    C2 --> D["InterviewSession.start()"]

    D --> E["LLMClient.check_health()<br/>GET /health/readiness"]
    E --> E1{Здоров?}
    E1 -->|Нет| E2[/"raise LLMClientError<br/>LLM API is not available"/]
    E2 --> ERR(["❌ Ошибка запуска"])

    E1 -->|Да| F["InterviewState(<br/>job_description=...)"]
    F --> G["session_id = uuid4()"]
    G --> H["LangfuseTracker.create_trace()"]
    H --> I["LLMClient.set_trace()"]
    I --> J["InterviewerAgent.generate_greeting()"]
    J --> J1["LLMClient.complete()<br/>generation_name=<br/>interviewer_greeting"]
    J1 --> K["InterviewTurn(greeting)"]
    K --> L["LangfuseTracker.add_span<br/>name=greeting"]
    L --> M(["return greeting<br/>✅ Интервью начато"])

    style E2 fill:#e53e3e,stroke:#c53030,color:#fff
    style ERR fill:#e53e3e,stroke:#c53030,color:#fff
    style M fill:#38a169,stroke:#276749,color:#fff
```

---

## 4. Workflow Observer — retry и парсинг

```mermaid
flowchart TD
    A(["ObserverAgent.process()"]) --> B["_build_analysis_context()"]
    B --> C["_build_messages()"]
    C --> D["attempt = 0"]

    D --> E["LLMClient.complete()<br/>generation_name=observer_analysis"]
    E --> F["extract_json_from_llm_response()"]
    F --> F1{JSON найден?}
    F1 -->|Да| G["_parse_analysis()"]
    G --> G1["_safe_parse_enum(ResponseType)"]
    G1 --> G2["_resolve_answered_last_question()"]
    G2 --> G3["Enforce: if not answered →<br/>should_simplify = false<br/>should_increase = false"]
    G3 --> G4["_parse_extracted_info()"]
    G4 --> H(["return ObserverAnalysis"])

    F1 -->|Нет| I{"attempt &lt;<br/>generation_retries?"}
    I -->|Да| J["attempt += 1<br/>log warning"]
    J --> E
    I -->|Нет| K[/"raise last_error"/]

    E --> E1{LLMClientError?}
    E1 -->|Да| K2[/"raise LLMClientError<br/>(немедленно, без retry)"/]

    style K fill:#e53e3e,stroke:#c53030,color:#fff
    style K2 fill:#e53e3e,stroke:#c53030,color:#fff
    style H fill:#38a169,stroke:#276749,color:#fff
```

---

## 5. Workflow LLMClient.complete() — retry и circuit breaker

```mermaid
flowchart TD
    A(["LLMClient.complete()"]) --> A1["compute_cache_key()<br/>SHA-256(model, messages,<br/>temperature, max_tokens, json_mode)"]
    A1 --> A2{"Cache hit?"}
    A2 -->|"Да"| A3(["return cached response<br/>(cost=0, Langfuse: cached=true)"])
    A2 -->|"Нет"| B["circuit_breaker.check()"]
    B --> B1{OPEN?}
    B1 -->|Да| B2[/"raise CircuitBreakerOpen"/]
    B1 -->|Нет| C["attempt = 0"]

    C --> D["POST /v1/chat/completions"]
    D --> D1{HTTP Status?}

    D1 -->|2xx| E["Parse JSON response"]
    E --> E1["Extract content, usage, cost"]
    E1 --> E2["LangfuseTracker.end_generation()"]
    E2 --> E3["circuit_breaker.record_success()"]
    E3 --> E4["cache.set(key, content, TTL)"]
    E4 --> F(["return content"])

    D1 -->|429, 500-504| G{"attempt &lt;<br/>max_retries?"}
    G -->|Да| G1["delay = base × 2^attempt<br/>(capped at max)"]
    G1 --> G2["await sleep(delay)"]
    G2 --> G3["attempt += 1"]
    G3 --> D
    G -->|Нет| G4["circuit_breaker.record_failure()<br/><i>(только 500–504, timeout,<br/>request error; НЕ 429)</i>"]
    G4 --> G5[/"raise LLMClientError<br/>Max retries exceeded"/]

    D1 -->|4xx (не 429)| H["end_generation_with_error()"]
    H --> H1[/"raise LLMClientError<br/>HTTP error"/]

    D --> T{Timeout?}
    T -->|Да| T1{"attempt &lt;<br/>max_retries?"}
    T1 -->|Да| G1
    T1 -->|Нет| G4

    D --> R{RequestError?}
    R -->|Да| R1{"attempt &lt;<br/>max_retries?"}
    R1 -->|Да| G1
    R1 -->|Нет| G4

    style B2 fill:#e53e3e,stroke:#c53030,color:#fff
    style G5 fill:#e53e3e,stroke:#c53030,color:#fff
    style H1 fill:#e53e3e,stroke:#c53030,color:#fff
    style A3 fill:#38a169,stroke:#276749,color:#fff
    style F fill:#38a169,stroke:#276749,color:#fff
```

---

## 6. Workflow адаптации сложности (комбинированный поток)

```mermaid
flowchart TD
    A(["Адаптация сложности<br/>(Observer → Session → State)"]) --> B{answered_last_question?}
    B -->|Нет| B1["should_simplify = false<br/>should_increase = false<br/><i>Инвариант: нельзя менять<br/>сложность без ответа</i>"]
    B1 --> Z([Без изменений])

    B -->|Да| C{should_increase_difficulty?}
    C -->|Да| D["consecutive_good += 1<br/>consecutive_bad = 0"]
    D --> D1{good_streak ≥ 2?}
    D1 -->|Да| D2["difficulty += 1<br/><i>(max: EXPERT)</i><br/>good_streak = 0"]
    D1 -->|Нет| Z

    C -->|Нет| E{should_simplify?}
    E -->|Да| F["consecutive_bad += 1<br/>consecutive_good = 0"]
    F --> F1{bad_streak ≥ 2?}
    F1 -->|Да| F2["difficulty -= 1<br/><i>(min: BASIC)</i><br/>bad_streak = 0"]
    F1 -->|Нет| Z

    E -->|Нет| G["consecutive_good = 0<br/>consecutive_bad = 0"]
    G --> Z

    D2 --> Z
    F2 --> Z

    style D2 fill:#38a169,stroke:#276749,color:#fff
    style F2 fill:#dd6b20,stroke:#c05621,color:#fff
    style B1 fill:#718096,stroke:#4a5568,color:#fff
```

---

## 7. Workflow определения answered_last_question

```mermaid
flowchart TD
    A(["_resolve_answered_last_question()"]) --> B{is_gibberish?}
    B -->|Да| C(["return False<br/><i>Бессмыслица → всегда<br/>не ответил</i>"])

    B -->|Нет| D{LLM вернул<br/>explicit bool?}
    D -->|Да| E(["return raw_value<br/><i>Прямое значение<br/>от LLM</i>"])

    D -->|Нет| F{response_type ∈<br/>UNANSWERED_TYPES?}
    F -->|Да| G(["return False<br/><i>OFF_TOPIC, QUESTION,<br/>STOP_COMMAND</i>"])
    F -->|Нет| H(["return True<br/><i>Fallback: считаем<br/>что ответил</i>"])

    style C fill:#e53e3e,stroke:#c53030,color:#fff
    style G fill:#e53e3e,stroke:#c53030,color:#fff
    style E fill:#4299e1,stroke:#2b6cb0,color:#fff
    style H fill:#38a169,stroke:#276749,color:#fff
```

---

## 8. Workflow Circuit Breaker — переходы состояний

```mermaid
stateDiagram-v2
    [*] --> CLOSED

    CLOSED --> CLOSED : record_success()
    CLOSED --> OPEN : record_failure()\n[count ≥ threshold]

    OPEN --> HALF_OPEN : recovery_timeout elapsed
    OPEN --> OPEN : check()\n[timeout not elapsed]\nraise CircuitBreakerOpen

    HALF_OPEN --> CLOSED : record_success()
    HALF_OPEN --> OPEN : record_failure()
```
