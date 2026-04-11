# Руководство для разработчиков

## Pre-commit

Установка git-хуков (выполняется один раз после клонирования репозитория):

```bash
pre-commit install
```

Запуск всех проверок вручную:

```bash
pre-commit run --all-files
```

---

## Линтеры и проверки

CI запускает четыре группы проверок: **black**, **isort**, **flake8** и **mypy**.
Ниже — команды для локального запуска каждой из них.

### Black (форматирование кода)

Проверка (без изменения файлов):

```bash
poetry run black --check --diff src/ tests/
```

Автоисправление:

```bash
poetry run black src/ tests/
```

### isort (порядок импортов)

Проверка:

```bash
poetry run isort --check-only --diff src/ tests/
```

Автоисправление:

```bash
poetry run isort src/ tests/
```

### Flake8 (стиль и сложность)

Проверка (только проверка, автоисправление не поддерживается):

```bash
poetry run flake8 src/ tests/
```

### Mypy (проверка типов)

```bash
poetry run mypy src/
```

---

## Быстрое автоисправление всех форматтеров

Одной командой — исправить форматирование и порядок импортов, затем проверить flake8 и mypy:

```bash
poetry run isort src/ tests/ \
  && poetry run black src/ tests/ \
  && poetry run flake8 src/ tests/ \
  && poetry run mypy src/
```

---

## Тесты

Запуск всех тестов с покрытием:

```bash
poetry run pytest tests/ --cov=src --cov-report=term-missing -ra -q
```

Быстрый запуск без отчёта о покрытии:

```bash
poetry run pytest tests/ --no-cov -ra -q
```

---

## Полная локальная проверка перед коммитом

Воспроизводит все шаги CI-пайплайна (lint → type-check → test):

```bash
poetry run isort src/ tests/ \
  && poetry run black src/ tests/ \
  && poetry run flake8 src/ tests/ \
  && poetry run mypy src/ \
  && poetry run pytest tests/ --cov=src --cov-report=term-missing -ra -q
```
