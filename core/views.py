import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def health(request):
    """Health-check: проверяет доступность БД и Redis (для мониторинга и Docker)."""
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        logger.exception("Health-check: database unavailable")
        checks["database"] = "error"

    try:
        cache.set("health", "1", timeout=5)
        checks["cache"] = "ok" if cache.get("health") == "1" else "error"
    except Exception:
        logger.exception("Health-check: cache unavailable")
        checks["cache"] = "error"

    healthy = all(v == "ok" for v in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )
