# C4 Component — Ядро системы (InterviewSession + Agents)

Диаграмма описывает внутреннее устройство ядра системы: оркестратор `InterviewSession` и его взаимодействие с агентами, LLM-клиентом и вспомогательными компонентами.

---

## Диаграмма

```mermaid
flowchart TB
    %% ── Оркестрация ──
    session["<b>InterviewSession</b><br/>Оркестратор: lifecycle, вызов агентов,<br/>мутации состояния, адаптация сложности"]
    state["<b>InterviewState</b><br/>In-memory: candidate, turns,<br/>difficulty, skills, gaps, streaks"]

    session <-->|"reads · mutates"| state

    %% ── Агенты ──
    subgraph agents[" Агенты "]
        direction LR
        observer["<b>ObserverAgent</b><br/>Анализ ответа: response_type,<br/>факт-чекинг, is_gibberish"]
        interviewer["<b>InterviewerAgent</b><br/>Генерация реплик и вопросов,<br/>обработка сценариев"]
        evaluator["<b>EvaluatorAgent</b><br/>Финальный фидбэк: verdict,<br/>technical_review, roadmap"]
    end

    base_agent["<b>BaseAgent</b> <i>ABC</i><br/>system_prompt, _build_messages(),<br/>_build_job_description_block()"]
    prompts["<b>Agent Prompts</b><br/>OBSERVER / INTERVIEWER / EVALUATOR<br/>system prompts"]

    %% ── LLM-инфраструктура ──
    subgraph llm[" LLM-инфраструктура "]
        direction LR
        llm_client["<b>LLMClient</b><br/>HTTP-клиент к LiteLLM:<br/>retry, backoff, cost extraction"]
        circuit_breaker["<b>CircuitBreaker</b><br/>CLOSED → OPEN → HALF_OPEN<br/>threshold: 5, recovery: 60s"]
        response_parser["<b>ResponseParser</b><br/>JSON: r-tag → result-tag →<br/>markdown → raw JSON"]
    end

    %% ── Observability ──
    subgraph obs[" Observability & Logging "]
        direction LR
        langfuse["<b>LangfuseTracker</b><br/>Traces, generations,<br/>spans, scores"]
        metrics["<b>SessionMetrics</b><br/>TokenUsage по агентам,<br/>cost_usd, turn_count"]
        logger["<b>InterviewLogger</b><br/>JSON-логи: interview_log<br/>и interview_detailed"]
    end

    %% ── Конфигурация ──
    subgraph cfg[" Конфигурация "]
        direction LR
        config["<b>Settings</b><br/>10 групп настроек,<br/>Pydantic Settings"]
        schemas["<b>Schemas</b><br/>InterviewTurn, ObserverAnalysis,<br/>InterviewFeedback, enums"]
    end

    %% ── Связи: основной поток ──
    session -->|"Stage 1: process()"| observer
    session -->|"greeting + Stage 5: process()"| interviewer
    session -->|"generate_feedback()"| evaluator

    %% ── Связи: иерархия агентов ──
    observer -.->|extends| base_agent
    interviewer -.->|extends| base_agent
    evaluator -.->|extends| base_agent
    base_agent -.->|"system_prompt"| prompts

    %% ── Связи: LLM вызовы ──
    session -.->|"health · set_trace · close"| llm_client
    base_agent -->|"provides _llm_client"| llm_client
    llm_client -->|"check · record"| circuit_breaker
    observer & evaluator -->|"extract_json()"| response_parser

    %% ── Связи: observability ──
    session -->|"save_session · save_raw_log"| logger
    session -->|"trace · spans · scores"| langfuse
    llm_client -->|"generation tracking"| langfuse
    langfuse -->|"add_generation · increment_turn"| metrics

    %% ── Связи: конфигурация ──
    session -.->|"settings"| config
    session -.->|"models"| schemas

    %% ── Стили ──
    classDef orch fill:#4A90D9,stroke:#2C5F8A,color:#fff
    classDef agent fill:#7B68EE,stroke:#5A4DB0,color:#fff
    classDef llmStyle fill:#E67E22,stroke:#BA6418,color:#fff
    classDef obsStyle fill:#27AE60,stroke:#1E8449,color:#fff
    classDef cfgStyle fill:#95A5A6,stroke:#707B7C,color:#fff

    class session,state orch
    class observer,interviewer,evaluator,base_agent,prompts agent
    class llm_client,circuit_breaker,response_parser llmStyle
    class langfuse,metrics,logger obsStyle
    class config,schemas cfgStyle
```

---

## Описание компонентов

### InterviewSession (оркестратор)

Центральный компонент, координирующий весь пайплайн обработки сообщения:

1. Принимает `user_message` от UI.
2. Записывает сообщение в последний `InterviewTurn`.
3. Вызывает `ObserverAgent.process()` — Stage 1.
4. Идемпотентно обновляет `CandidateInfo` — Stage 2.
5. Проверяет стоп-команду — Stage 3.
6. Корректирует сложность (с snapshot для отката) — Stage 4.
7. Вызывает `InterviewerAgent.process()` — Stage 5. При сбое → откат difficulty.
8. Фиксирует неидемпотентные мутации (topics, skills, gaps) — Stage 6.

При завершении вызывает `EvaluatorAgent.process()` и сохраняет логи.

### Agents (Observer / Interviewer / Evaluator)

Все наследуются от `BaseAgent`, который предоставляет:

- `system_prompt` — абстрактное свойство, реализуемое каждым агентом;
- `_build_messages(user_content, history)` — формирование списка сообщений с правильным чередованием ролей;
- `_build_job_description_block(job_description)` — XML-блок описания вакансии.

**Observer** и **Evaluator** поддерживают `generation_retries` (default: 2) — повторные генерации при ошибке парсинга JSON. **Interviewer** не использует retry (`generation_retries=0`), т.к. генерирует свободный текст.

### LLMClient

- `complete()` — текстовый запрос с retry и backoff.
- `complete_json()` — JSON-запрос с fallback на текстовый режим при HTTP 400.
- `check_health()` — проверка `/health/readiness` перед стартом сессии.
- Интегрирован с `CircuitBreaker` для защиты от каскадных сбоев.
- Создаёт Langfuse `generation` на каждый вызов.

### ResponseParser

Четыре стратегии извлечения JSON (по убыванию приоритета):

1. `<r>...</r>` теги.
2. `<result>...</result>` теги.
3. Markdown code block (`` ```json ... ``` ``).
4. Сырой JSON-объект `{...}` с поиском сбалансированных скобок.

Также извлекает `<reasoning>...</reasoning>` блок для отладки.

### InterviewState

Pydantic `BaseModel` с мутабельными полями:

- `turns: list[InterviewTurn]` — полная история.
- `current_difficulty: DifficultyLevel` — BASIC/INTERMEDIATE/ADVANCED/EXPERT.
- `adjust_difficulty(analysis)` — детерминированный алгоритм на основе streak.
- `get_conversation_history(max_turns)` — формирует список `role/content` для LLM.

### SessionMetrics

Dataclass, агрегирующий:

- `TokenUsage` (input/output/total/cost) по каждому агенту (observer, interviewer, evaluator) и суммарно.
- `turn_count`, `generation_count`.
- Вычисляемые (при записи в Langfuse): `avg_tokens_per_turn`, `session_cost_usd`.

Метрики добавляются в Langfuse trace как span и scores при завершении сессии, а также записываются в детальный JSON-лог.