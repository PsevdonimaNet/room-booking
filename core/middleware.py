import logging
import time

from . import db_guard

logger = logging.getLogger("requests")
db_logger = logging.getLogger("core.db")


def _username(request):
    """Имя пользователя для журнала. Не обращается к БД, если она недоступна."""
    if db_guard.is_open():
        return "unknown"
    try:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return user.username
        return "anonymous"
    except db_guard.DB_ERRORS:
        db_guard.mark_failure()
        return "unknown"


class RequestLogMiddleware:
    """Логирует каждый HTTP-запрос: метод, путь, статус, пользователь, время ответа."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        if request.path == "/metrics":
            return response  # опрос Prometheus не засоряет журнал
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s -> %s user=%s %.1f ms",
            request.method,
            request.path,
            response.status_code,
            _username(request),
            elapsed_ms,
        )
        return response


class DatabaseGuardMiddleware:
    """Быстрый отказ 503 при недоступной БД (см. core.db_guard).

    Стоит последним в списке MIDDLEWARE, чтобы ответы 503 попадали в метрики Prometheus.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if db_guard.is_open() and request.path not in db_guard.EXEMPT_PATHS:
            return db_guard.unavailable_response()
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, db_guard.DB_ERRORS):
            db_guard.mark_failure()
            db_logger.error("БД недоступна: %s %s (%s)", request.method, request.path, exception)
            return db_guard.unavailable_response()
        return None
