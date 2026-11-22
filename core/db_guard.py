"""Защита от недоступной БД: быстрый отказ (503) вместо зависания запросов.

Состояние хранится отдельно в каждом процессе gunicorn. После ошибки соединения с БД
в течение OPEN_SECONDS запросы сразу получают 503, не тратя потоки на ожидание.
"""

import time

from django.db.utils import InterfaceError, OperationalError
from django.http import JsonResponse

OPEN_SECONDS = 5
# Эти адреса всегда обрабатываются: по ним мониторинг определяет, что БД снова доступна
EXEMPT_PATHS = ("/health/", "/metrics")
DB_ERRORS = (OperationalError, InterfaceError)
MESSAGE = "Сервис временно недоступен: нет связи с базой данных. Повторите попытку позже."

_failed_at = None


def mark_failure():
    global _failed_at
    _failed_at = time.monotonic()


def reset():
    global _failed_at
    _failed_at = None


def is_open():
    return _failed_at is not None and time.monotonic() - _failed_at < OPEN_SECONDS


def error_payload():
    return {"error": {"code": "service_unavailable", "message": MESSAGE, "details": {}}}


def unavailable_response():
    response = JsonResponse(error_payload(), status=503)
    response["Retry-After"] = str(OPEN_SECONDS)
    return response
