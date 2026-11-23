# Архитектура

Схемы написаны на Mermaid и отображаются на GitHub.

## 1. Контекст системы (C4, уровень 1)

```mermaid
flowchart LR
    user["Сотрудник<br/>(пользователь)"]
    admin["Администратор"]
    system["Система бронирования<br/>переговорных комнат"]
    mon["Мониторинг<br/>Prometheus + Grafana"]
    ci["GitHub Actions<br/>(CI/CD)"]
    user -->|"просмотр, бронирование"| system
    admin -->|"управление, подтверждение, отчёты"| system
    mon -->|"сбор метрик /metrics"| system
    ci -->|"сборка, тесты, публикация образа"| system
```

## 2. Контейнеры (C4, уровень 2)

```mermaid
flowchart TB
    browser["Браузер / Swagger UI"]
    subgraph compose["Docker Compose"]
        nginx["Nginx (reverse proxy)<br/>рекомендуется для продакшена"]
        web["Django + Gunicorn<br/>веб-интерфейс и REST API"]
        db[("PostgreSQL 16")]
        redis[("Redis 7<br/>кэш и сессии")]
        pgexp["postgres-exporter"]
        prom["Prometheus"]
        graf["Grafana"]
    end
    browser -->|"HTTPS"| nginx
    nginx -->|"HTTP"| web
    web -->|"SQL"| db
    web -->|"сессии, кэш"| redis
    pgexp -->|"статистика БД"| db
    prom -->|"scrape /metrics"| web
    prom -->|"scrape"| pgexp
    graf -->|"запросы PromQL"| prom
```

В демо-стенде браузер обращается к Gunicorn напрямую (порт 8000), Nginx не используется.

## 3. Компоненты приложения (C4, уровень 3)

```mermaid
flowchart LR
    subgraph config["config"]
        settings["settings, urls"]
    end
    subgraph core["core"]
        health["health-check"]
        mw["middleware:<br/>RequestLog, DatabaseGuard"]
        guard["db_guard<br/>(быстрый отказ при сбое БД)"]
    end
    subgraph bookings["bookings"]
        models["models:<br/>Room, Booking, Role,<br/>Profile, Notification"]
        services["services:<br/>правила бронирования,<br/>конфликты, подтверждение"]
        api["API: serializers, views,<br/>permissions"]
        reports["reports: сводка, CSV"]
        notif["notifications"]
        adm["admin"]
    end
    subgraph web["web"]
        views["views, forms"]
        tpl["templates"]
    end
    views --> services
    api --> services
    services --> models
    services --> notif
    api --> reports
    views --> reports
    mw --> guard
    health --> guard
    views --> tpl
```

Бизнес-правила находятся в `bookings/services.py` и используются и веб-интерфейсом, и API. Это исключает расхождение логики.

## 4. Модель данных

```mermaid
erDiagram
    USER ||--|| PROFILE : "имеет"
    ROLE ||--o{ PROFILE : "назначена"
    USER ||--o{ BOOKING : "создаёт"
    ROOM ||--o{ BOOKING : "бронируется"
    USER ||--o{ NOTIFICATION : "получает"
    ROLE {
        bigint id PK
        varchar code UK
        varchar name
    }
    PROFILE {
        bigint id PK
        bigint user_id FK
        bigint role_id FK
    }
    ROOM {
        bigint id PK
        varchar name UK
        smallint capacity
        varchar location
        text description
        boolean is_active
        boolean is_vip
    }
    BOOKING {
        bigint id PK
        bigint user_id FK
        bigint room_id FK
        timestamptz start
        timestamptz end_time "столбец end в БД"
        varchar status "pending, confirmed, cancelled, rejected"
        timestamptz created_at
        timestamptz cancelled_at
    }
    NOTIFICATION {
        bigint id PK
        bigint user_id FK
        varchar text
        timestamptz created_at
        boolean is_read
    }
```

Ограничение БД: время окончания строго позже начала. Индекс по комнате и интервалу ускоряет поиск пересечений. Пользователь (`USER`) это стандартная модель Django.

## 5. Поток данных: бронирование и конфликт

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant W as Web или API
    participant S as create_booking
    participant DB as PostgreSQL
    U->>W: POST /api/bookings/ (комната, начало, конец)
    W->>S: create_booking(user, room, start, finish)
    S->>S: проверка правил (целые часы, 1-4 ч, 8-20, не в прошлом)
    S->>DB: BEGIN, блокировка строки комнаты
    S->>DB: поиск пересекающихся броней (pending, confirmed)
    alt есть пересечение
        S->>DB: COMMIT (изменений нет)
        S->>DB: уведомления обоим пользователям
        S-->>W: BookingConflict
        W-->>U: 409 booking_conflict
    else свободно
        S->>DB: INSERT booking (confirmed, для VIP pending)
        S->>DB: COMMIT
        S-->>W: бронь
        W-->>U: 201 Created
    end
```

Блокировка строки комнаты (`SELECT ... FOR UPDATE`) выстраивает параллельные запросы на одну комнату по очереди, поэтому двойное бронирование невозможно.

## 6. Схема развёртывания

```mermaid
flowchart LR
    dev["Разработчик"] -->|"git push"| gh["GitHub"]
    gh -->|"Actions: lint, test, build"| ghcr["GHCR<br/>образ Docker"]
    gh -->|"Blueprint"| render["Render<br/>демо-стенд"]
    dev -->|"docker compose up"| local["Локальный стенд<br/>web, db, redis,<br/>Prometheus, Grafana"]
```

## 7. Внешние интеграции

В MVP внешних бизнес-интеграций нет. Технические: GitHub (код, CI, образы), Prometheus/Grafana (мониторинг), хостинг демо-стенда (Render).
