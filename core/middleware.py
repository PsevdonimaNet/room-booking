import logging
import time

logger = logging.getLogger("requests")


class RequestLogMiddleware:
    """Логирует каждый HTTP-запрос: метод, путь, статус, пользователь, время ответа."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        user = getattr(request, "user", None)
        username = user.username if user is not None and user.is_authenticated else "anonymous"
        logger.info(
            "%s %s -> %s user=%s %.1f ms",
            request.method,
            request.path,
            response.status_code,
            username,
            elapsed_ms,
        )
        return response
