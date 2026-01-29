#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# Set variables
GRAFANA_URL="${GRAFANA_URL:-}"             # Базовый URL Grafana (например https://grafana.example.com)
GRAFANA_API_KEY="${GRAFANA_API_KEY:-}"     # API ключ Grafana (Bearer token) для загрузки дашбордов
DASHBOARD_DIR="${DASHBOARD_DIR:-}"         # Директория с *.json дашбордами для загрузки
COMMIT_MESSAGE="${COMMIT_MESSAGE:-}"       # Сообщение, которое попадет в историю версий дашборда Grafana
UNIX_TIMESTAMP="${UNIX_TIMESTAMP:-}"       # Таймстамп, используется для уникализации message (и/или трассировки деплоя)

require_bin() {
    local name="$1"                        # Имя бинарника, наличие которого нужно проверить
    command -v "$name" >/dev/null 2>&1 || {
        echo "Missing required binary: $name" >&2
        exit 2
    }
}

require_non_empty() {
    local name="$1"                        # Имя переменной окружения (для сообщения об ошибке)
    local value="$2"                       # Значение переменной окружения для проверки
    if [[ -z "${value//[[:space:]]/}" ]]; then
        echo "Missing required environment variable: $name" >&2
        exit 2
    fi
}

require_uint() {
    local name="$1"                        # Имя переменной окружения (для сообщения об ошибке)
    local value="$2"                       # Значение, которое должно быть неотрицательным целым
    if [[ ! "$value" =~ ^[0-9]+$ ]]; then
        echo "Invalid unsigned integer in environment variable: $name" >&2
        exit 2
    fi
}

require_bin curl
require_bin jq
require_non_empty "GRAFANA_URL" "$GRAFANA_URL"
require_non_empty "GRAFANA_API_KEY" "$GRAFANA_API_KEY"
require_non_empty "DASHBOARD_DIR" "$DASHBOARD_DIR"
require_non_empty "COMMIT_MESSAGE" "$COMMIT_MESSAGE"
require_non_empty "UNIX_TIMESTAMP" "$UNIX_TIMESTAMP"
require_uint "UNIX_TIMESTAMP" "$UNIX_TIMESTAMP"

if [[ ! -d "$DASHBOARD_DIR" ]]; then
    echo "Dashboard directory does not exist: $DASHBOARD_DIR" >&2
    exit 2
fi

curl_get_json_status() {
    local url="$1"                         # URL, по которому делаем GET
    local tmp
    tmp="$(mktemp)"                        # Временный файл для тела ответа, чтобы отдельно достать HTTP код
    local code="000"
    code="$(curl -sS -o "$tmp" -w "%{http_code}" \
        --header "Authorization: Bearer $GRAFANA_API_KEY" \
        --header 'Accept: application/json' \
        "$url" || true)"                   # Ошибки curl не валят скрипт (код обработаем ниже)
    cat "$tmp"                             # Выводим тело ответа
    rm -f "$tmp"                           # Удаляем временный файл
    printf '\n%s\n' "$code"                # Выводим HTTP статус отдельной строкой (последней)
}

# Function to update a single dashboard
update_dashboard() {
    local dashboard_file="$1"              # Путь к файлу дашборда (*.json)

    # Read the dashboard JSON content
    local dashboard_json
    dashboard_json="$(<"$dashboard_file")" # Чтение файла без запуска внешних утилит

    echo "$dashboard_json" | jq -e . >/dev/null 2>&1 || {
        echo "Invalid JSON in dashboard file: $dashboard_file" >&2
        exit 2
    }

    local uid
    uid="$(echo "$dashboard_json" | jq -r '.uid // empty')"  # UID дашборда (ключ для поиска в Grafana)

    local current_id="null"                # Текущий id в Grafana (для overwrite без создания дублей)
    local current_version="0"              # Текущая version в Grafana (для корректного обновления)

    if [[ -n "${uid//[[:space:]]/}" ]]; then
        local body_and_code
        body_and_code="$(curl_get_json_status "$GRAFANA_URL/api/dashboards/uid/$uid")" # Получаем dashboard по UID (тело + код)

        local code
        code="$(printf '%s' "$body_and_code" | tail -n 1)"     # Последняя строка — HTTP код

        local body
        body="$(printf '%s' "$body_and_code" | sed '$d')"      # Все кроме последней строки — JSON тело

        if [[ "$code" == "200" ]]; then
            current_id="$(echo "$body" | jq -r '.dashboard.id')"           # Внутренний id дашборда в Grafana
            current_version="$(echo "$body" | jq -r '.dashboard.version')" # Версия дашборда в Grafana
            [[ "$current_id" =~ ^[0-9]+$ ]] || {
                echo "Unexpected dashboard.id from Grafana for uid=$uid" >&2
                exit 2
            }
            [[ "$current_version" =~ ^[0-9]+$ ]] || {
                echo "Unexpected dashboard.version from Grafana for uid=$uid" >&2
                exit 2
            }
        elif [[ "$code" == "404" ]]; then
            current_id="null"               # Дашборда нет — создадим новый
            current_version="0"
        else
            echo "Failed to fetch dashboard by uid=$uid (HTTP $code)" >&2
            echo "$body" >&2
            exit 2
        fi
    fi

    # replace version with unix timestamp
    local updated_version
    updated_version="$(echo "$dashboard_json" | jq \
        --argjson id "$current_id" \
        --argjson ver "$current_version" \
        '.id = $id | .version = $ver')"    # Подставляем id/version из Grafana, чтобы overwrite работал предсказуемо

    # Wrap the dashboard JSON in the required structure
    local payload
    payload="$(jq -c -n \
        --arg commit_message "$COMMIT_MESSAGE" \
        --arg ts "$UNIX_TIMESTAMP" \
        --argjson dashboard "$updated_version" \
        '{
            dashboard: $dashboard,
            folderId: 0,
            overwrite: true,
            message: ($commit_message + " (ts=" + $ts + ")")
        }')"                                # Формируем payload для POST /api/dashboards/db

    curl --fail-with-body --location "$GRAFANA_URL/api/dashboards/db" \
        --header 'Content-Type: application/json' \
        --header 'Accept: application/json' \
        --header "Authorization: Bearer $GRAFANA_API_KEY" \
        --data "$payload" \
        >/dev/null                           # Загрузка дашборда в Grafana (без вывода тела ответа)
}

# Loop through all JSON files in the dashboard directory
shopt -s nullglob                            # Если файлов нет — glob расширится в пустой список, а не в литерал "*.json"
for dashboard_file in "$DASHBOARD_DIR"/*.json; do
    if [ -f "$dashboard_file" ]; then        # Защита от странных совпадений glob
        update_dashboard "$dashboard_file"   # Обновление/создание дашборда
    fi
done