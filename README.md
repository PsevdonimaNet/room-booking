# Сервис бронирования переговорных комнат (MVP)

Веб-приложение для бронирования переговорных в офисе.
Стек: Python 3.12, Django 5, PostgreSQL 16, Redis 7, Docker, GitHub Actions.

## Быстрый старт (Docker)

```bash
cp .env.example .env
docker compose up --build
```

- Приложение: http://localhost:8000
- Админ-панель: http://localhost:8000/admin/
- Health-check: http://localhost:8000/health/

Создать администратора:

```bash
docker compose exec web python manage.py createsuperuser
```

## Локальная разработка

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
docker compose up -d db redis
POSTGRES_HOST=localhost REDIS_URL=redis://localhost:6379/1 python manage.py migrate
python manage.py runserver
```

## Проверки качества

```bash
ruff check .            # линтер
ruff format .           # форматирование
coverage run manage.py test && coverage report   # тесты и покрытие (порог 70%)
```

## CI/CD

При каждом push GitHub Actions запускает: линтер -> тесты с покрытием (артефакт `coverage.xml`) -> сборка Docker-образа.
В ветке `main` образ публикуется в GitHub Container Registry (`ghcr.io/<user>/<repo>:latest`).

## Структура

```
config/   настройки проекта, urls
core/     общие вещи: health-check
```
