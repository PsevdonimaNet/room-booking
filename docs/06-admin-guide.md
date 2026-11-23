# Руководство администратора

## 1. Установка

Требования: Docker Desktop (или Docker Engine + Compose), Git.

```bash
git clone https://github.com/<логин>/room-booking.git
cd room-booking
cp .env.example .env        # Windows: copy .env.example .env
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo   # необязательно: демо-данные
```

Сайт: http://localhost:8000, админ-панель: http://localhost:8000/admin/, API: `/api/docs/`, проверка здоровья: `/health/`.

Миграции применяются автоматически при запуске контейнера `web`.

## 2. Настройка (файл `.env`)

| Переменная | Назначение | Пример |
|---|---|---|
| `DJANGO_SECRET_KEY` | секретный ключ (в продакшене уникальный и длинный) | случайная строка |
| `DJANGO_DEBUG` | режим отладки (в продакшене `0`) | `0` |
| `DJANGO_ALLOWED_HOSTS` | допустимые адреса через запятую | `example.com,localhost` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | подключение к БД | `booking`, `db`, `5432` |
| `REDIS_URL` | кэш и сессии; без него кэш в памяти процесса (подходит для одного процесса) | `redis://redis:6379/1` |
| `WEB_CONCURRENCY`, `WEB_THREADS` | число процессов и потоков Gunicorn | `4`, `4` |
| `DJANGO_LOG_LEVEL` | уровень журнала | `INFO` |
| `DJANGO_BEHIND_PROXY`, `DJANGO_CSRF_TRUSTED_ORIGINS` | работа за HTTPS-прокси | `1`, `https://example.com` |
| `USE_SQLITE` | запуск без PostgreSQL (только для разработки) | `1` |

Правила бронирования (рабочее время, длительность) задаются в `config/settings.py` (`BOOKING_*`), часовой пояс в `TIME_ZONE`.

## 3. Ежедневная работа

**Пользователи и роли.** Раздел «Пользователи и роли» (`/manage/users/`): выбрать роль и нажать «Назначить». Менять роль самому себе нельзя. Суперпользователь Django всегда имеет права администратора. Новых пользователей можно создавать в админ-панели или они регистрируются сами.

**Комнаты.** «Управление комнатами» (`/manage/rooms/`): добавление, изменение, флаги «VIP» и «Доступна для бронирования». Отключённая комната скрыта от пользователей, история её броней сохраняется.

**VIP-заявки.** Страница «Заявки» (`/manage/pending/`, в меню счётчик): «Подтвердить» или «Отклонить». Ожидающая заявка занимает слот; отклонённая освобождает. Пользователь получает уведомление о решении.

**Отчёты.** «Отчёты» (`/manage/report/`): фильтры по датам, комнате, статусу; сводка по комнатам; «Скачать CSV» (UTF-8 с BOM, разделитель `;`, открывается в Excel).

## 4. Мониторинг

Запуск вместе с основным стеком:

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up --build -d
```

| Сервис | Адрес |
|---|---|
| Grafana (admin / admin, сменить пароль) | http://localhost:3000 |
| Prometheus, алерты | http://localhost:9090/alerts |
| Метрики приложения | http://localhost:8000/metrics |

Алерты: `ServiceDown`, `AvailabilityBelowSLA`, `HighErrorRate`, `HighLatencyP95`, `DatabaseDown`, `DatabaseConnectionsHigh`. Подробности: `monitoring-and-testing.md`. В продакшене закройте `/metrics` на уровне Nginx или сети и настройте Alertmanager для уведомлений.

## 5. Журналы

- Файл `logs/app.log` (ротация 5 МБ, 3 копии) и вывод контейнера: `docker compose logs -f web`.
- В журнале: каждый HTTP-запрос (метод, путь, статус, пользователь, время), создание, отмена, подтверждение броней, конфликты, изменения комнат и ролей, ошибки.
- Поиск конфликтов: `docker compose exec web sh -c "grep 'Конфликт' logs/app.log | tail"`.

## 6. Резервное копирование и восстановление

**Копия** (формат custom, без проблем с кодировкой в PowerShell):

```bash
docker compose exec db sh -c "pg_dump -U booking -Fc booking > /tmp/backup.dump"
docker compose cp db:/tmp/backup.dump ./backup-$(date +%F).dump    # Windows: ./backup.dump
```

**Восстановление:**

```bash
docker compose cp ./backup.dump db:/tmp/backup.dump
docker compose exec db pg_restore -U booking -d booking --clean --if-exists /tmp/backup.dump
```

Рекомендации: делать копию ежедневно (cron на сервере), хранить 7 копий вне сервера, раз в месяц проверять восстановление на тестовой БД. Redis хранит только кэш и сессии, копировать его не нужно.

## 7. Обновление

```bash
git pull
docker compose up --build -d    # миграции применятся автоматически
docker compose exec web python manage.py test   # проверка (по желанию)
```

Перед обновлением сделайте резервную копию БД.

## 8. Устранение неполадок

| Симптом | Причина и действия |
|---|---|
| Сайт отвечает 503 `service_unavailable` | недоступна БД: `docker compose ps`, `docker compose logs db`; после запуска БД сервис восстановится сам |
| `/health/` показывает `degraded` | в `checks` указано, что недоступно (`database` или `cache`) |
| 403 на страницах `/manage/*` | у пользователя нет роли администратора |
| Не открывается Grafana или Prometheus | запущен ли стек с `docker-compose.monitoring.yml` |
| Порт 8000 занят | изменить порт в `docker-compose.yml` |
| Ошибки CSRF за прокси | задать `DJANGO_BEHIND_PROXY=1` и `DJANGO_CSRF_TRUSTED_ORIGINS` |
| Контейнер `web` в статусе `unhealthy` | `docker compose logs web`, проверить `.env` и доступность БД |

## 9. Безопасность

Смените пароли по умолчанию (Grafana, демо-пользователи), задайте уникальный `DJANGO_SECRET_KEY`, отключите `DJANGO_DEBUG`, используйте HTTPS (Nginx), ограничьте доступ к `/metrics`, регулярно обновляйте зависимости (`pip-audit` в CI показывает известные уязвимости; текущие замечания в реестре дефектов D-009).
