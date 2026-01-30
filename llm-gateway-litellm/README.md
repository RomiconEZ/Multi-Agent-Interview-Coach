# llm-gateway-litellm

Шлюз LLM на базе LiteLLM с хранением конфигурации моделей и логов в PostgreSQL. Проект поднимается через Docker Compose.

## Состав

- **LiteLLM** (контейнер `litellm`) — HTTP API совместимый с OpenAI API, маршрутизация запросов к нескольким бэкендам, управление моделями, healthchecks.
- **PostgreSQL** (контейнер `litellm_db`) — хранение данных LiteLLM (модели/настройки/логи) при включенном `STORE_MODEL_IN_DB`.

## Требования

- Docker
- Docker Compose

## Быстрый старт

1. Создать файл `.env` из примера:
   ```bash
   cp .env.example .env
   ```

2. Заполнить значения в `.env`:
   - ключи LiteLLM: `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`
   - при использовании DeepSeek: `DEEPSEEK_API_KEY`
   - при использовании локального бэкенда: `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_API_KEY`

3. Запустить сервисы:
   ```bash
   docker compose up -d
   ```

4. Проверить готовность:
   ```bash
   curl -sS http://localhost:${LITELLM_PORT_EXTERNAL}/health/liveliness
   ```

5. Остановить:
   ```bash
   docker compose down
   ```

## Порты

Значения задаются в `.env`:

- **LiteLLM**: `${LITELLM_PORT_EXTERNAL}` → `4000` (внутри контейнера)
- **PostgreSQL**: `${POSTGRES_PORT_EXTERNAL}` → `5432` (внутри контейнера)

## Переменные окружения

Файл `.env.example` содержит полный набор параметров. Основные группы:

### LiteLLM

- `LITELLM_MASTER_KEY` — мастер-ключ LiteLLM.
- `LITELLM_SALT_KEY` — ключ для хэширования/соли LiteLLM.
- `STORE_MODEL_IN_DB` — сохранять модели в БД (`true/false`).

### UI (если используется)

- `UI_USERNAME`, `UI_PASSWORD` — учетные данные для админ-панели.

### Образы

- `LITELLM_IMAGE_TAG` — тег образа LiteLLM.
- `POSTGRES_IMAGE_TAG` — тег образа PostgreSQL.

### PostgreSQL

- `POSTGRES_DB` — имя БД.
- `POSTGRES_USER` — пользователь БД.
- `POSTGRES_PASSWORD` — пароль пользователя БД.

### Бэкенды моделей

- `LOCAL_LLM_BASE_URL` — базовый URL локального OpenAI-совместимого бэкенда (например LM Studio).
- `LOCAL_LLM_API_KEY` — API ключ локального бэкенда.
- `DEEPSEEK_BASE_URL` — базовый URL API DeepSeek.
- `DEEPSEEK_API_KEY` — API ключ DeepSeek.

## Конфигурация LiteLLM

Конфигурация задается в `config.yaml` и монтируется в контейнер LiteLLM как `/app/config.yaml`.

### model_list

Определены модели:

- `local_llm`
  - `model`: `lm_studio/local_llm`
  - `api_base`: `LOCAL_LLM_BASE_URL`
  - `api_key`: `LOCAL_LLM_API_KEY`

- `cloud/deepseek-chat`
  - `model`: `deepseek/deepseek-chat`
  - `api_base`: `DEEPSEEK_BASE_URL`
  - `api_key`: `DEEPSEEK_API_KEY`
  - `model_info.custom_tokenizer`: `deepseek-ai/DeepSeek-V3.2`

- `cloud/deepseek-coder`
  - `model`: `deepseek/deepseek-coder`
  - `api_base`: `DEEPSEEK_BASE_URL`
  - `api_key`: `DEEPSEEK_API_KEY`
  - `model_info.custom_tokenizer`: `deepseek-ai/DeepSeek-V3.2`

- `cloud/deepseek-reasoner`
  - `model`: `deepseek/deepseek-reasoner`
  - `api_base`: `DEEPSEEK_BASE_URL`
  - `api_key`: `DEEPSEEK_API_KEY`
  - `model_info.custom_tokenizer`: `deepseek-ai/DeepSeek-V3.2`

### general_settings

- `store_model_in_db: true` — хранить модели в БД.
- `store_prompts_in_spend_logs: true` — сохранять промпты в логах расходов.

### litellm_settings

- `request_timeout: 1800` — таймаут запросов (сек).
- `set_verbose: False` — отключение подробного логирования.
- `json_logs: true` — JSON формат логов.

## Docker Compose

Файл `docker-compose.yml` поднимает сервисы:

### litellm

- Образ: `docker.litellm.ai/berriai/litellm:${LITELLM_IMAGE_TAG}`
- Порт: `4000` (наружу пробрасывается `LITELLM_PORT_EXTERNAL`)
- Том: `./config.yaml:/app/config.yaml`
- Переменные:
  - `DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}`
  - `STORE_MODEL_IN_DB=${STORE_MODEL_IN_DB}`
- Healthcheck:
  - `http://localhost:4000/health/liveliness`

### db

- Образ: `postgres:${POSTGRES_IMAGE_TAG}`
- Порт: `5432` (наружу пробрасывается `POSTGRES_PORT_EXTERNAL`)
- Том данных: `litellm_postgres_data`
- Healthcheck:
  - `pg_isready -d litellm -U llmproxy`

## Использование API

LiteLLM предоставляет OpenAI-совместимые эндпоинты на `http://localhost:${LITELLM_PORT_EXTERNAL}`.

Пример списка моделей:
```bash
curl -sS http://localhost:${LITELLM_PORT_EXTERNAL}/v1/models
```

В запросах используйте `model` из `config.yaml` (например `local_llm` или `cloud/deepseek-chat`).

## Структура репозитория

- `.env.example` — пример переменных окружения.
- `docker-compose.yml` — запуск LiteLLM и PostgreSQL.
- `config.yaml` — конфигурация моделей и настроек LiteLLM.
- `.gitignore` — исключения для Git.
- `README.md` — описание проекта.

## Диагностика

Логи контейнеров:
```bash
docker compose logs -f litellm
docker compose logs -f db
```

Проверка состояния контейнеров:
```bash
docker compose ps
```

Проверка доступности БД с хоста:
```bash
psql "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT_EXTERNAL}/${POSTGRES_DB}"
```
