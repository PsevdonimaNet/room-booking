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

## API

Документация (Swagger UI): http://localhost:8000/api/docs/ - кнопка **Authorize**, логин и пароль пользователя.
Схема OpenAPI: http://localhost:8000/api/schema/

| Метод | Адрес | Описание | Доступ |
|---|---|---|---|
| GET | `/api/rooms/` | Список переговорных | все авторизованные |
| POST/PUT/PATCH/DELETE | `/api/rooms/{id}/` | CRUD комнат (DELETE - мягкое отключение) | администратор |
| GET | `/api/rooms/{id}/availability/?date=YYYY-MM-DD` | Занятость по часам | все авторизованные |
| POST | `/api/bookings/` | Бронирование `{room, start, end}` | все авторизованные |
| GET | `/api/bookings/?room=<id>` | История (свои; админ - все) | все авторизованные |
| POST | `/api/bookings/{id}/cancel/` | Отмена | владелец или админ |
| POST | `/api/bookings/{id}/approve/`, `/reject/` | Подтвердить / отклонить бронь VIP-комнаты | администратор |
| GET | `/api/bookings/export/?date_from=&date_to=&room=&status=` | Экспорт в CSV (UTF-8 BOM, разделитель `;`) | администратор |

VIP-комнаты (`is_vip`): бронь создаётся со статусом `pending` и ждёт решения администратора.
Статусы: `pending`, `confirmed`, `cancelled`, `rejected`. Ожидающая бронь занимает слот.

Правила: целые часы, длительность 1-4 ч, рабочее время 08:00-20:00, не в прошлом.
Ошибки: `{"error": {"code": "...", "message": "...", "details": {}}}`.
Коды: 400 `validation_error`, 403 `forbidden`, 409 `booking_conflict` / `invalid_state`.

## Запуск без Docker (запасной вариант)

```bash
USE_SQLITE=1 python manage.py migrate
USE_SQLITE=1 python manage.py runserver
```
(PowerShell: `$env:USE_SQLITE="1"` перед командами)

## Мониторинг и нагрузочное тестирование

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up --build -d
docker compose exec web python manage.py seed_demo --load-users 20
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml --profile load run --rm k6
```

Prometheus: http://localhost:9090, Grafana: http://localhost:3000 (admin / admin), метрики: `/metrics`.
Подробности, SLA, алерты и методика стресс-теста: `docs/monitoring-and-testing.md`.

## Публикация демо-стенда

Бесплатный хостинг (Render) и временная ссылка (Cloudflare Tunnel): `docs/deployment.md`, настройки Render: `render.yaml`.

## Структура

```
config/   настройки проекта, urls
core/     общие вещи: health-check, логирование запросов
bookings/ модели, сервисы, API, админка бронирования
```
