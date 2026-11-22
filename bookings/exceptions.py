from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core import db_guard


class DomainError(Exception):
    """Бизнес-ошибка с понятным кодом и сообщением для клиента API."""

    status_code = 400
    code = "error"

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class BookingValidationError(DomainError):
    status_code = 400
    code = "validation_error"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "forbidden"


class BookingConflict(DomainError):
    status_code = 409
    code = "booking_conflict"


class BookingStateError(DomainError):
    status_code = 409
    code = "invalid_state"


def api_exception_handler(exc, context):
    """Единый формат ошибок: {"error": {"code", "message", "details"}}."""
    if isinstance(exc, DomainError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            status=exc.status_code,
        )
    if isinstance(exc, db_guard.DB_ERRORS):
        db_guard.mark_failure()
        return Response(db_guard.error_payload(), status=503, headers={"Retry-After": "5"})
    return drf_exception_handler(exc, context)
