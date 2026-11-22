import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .exceptions import (
    BookingConflict,
    BookingStateError,
    BookingValidationError,
    PermissionDeniedError,
)
from .models import Booking, Role, Room

logger = logging.getLogger("bookings")


def is_admin(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    return profile is not None and profile.role.code == Role.ADMIN


def validate_interval(start, end, now=None):
    """Проверка правил бронирования: целые часы, 1-4 часа, рабочее время, не в прошлом."""
    now = now or timezone.now()
    if end <= start:
        raise BookingValidationError("Время окончания должно быть позже времени начала.")

    local_start, local_end = timezone.localtime(start), timezone.localtime(end)
    for moment in (local_start, local_end):
        if moment.minute or moment.second or moment.microsecond:
            raise BookingValidationError("Бронирование возможно только на целые часы.")

    hours = (end - start).total_seconds() / 3600
    if not settings.BOOKING_MIN_HOURS <= hours <= settings.BOOKING_MAX_HOURS:
        raise BookingValidationError(
            f"Длительность бронирования: от {settings.BOOKING_MIN_HOURS} "
            f"до {settings.BOOKING_MAX_HOURS} часов."
        )
    if start < now:
        raise BookingValidationError("Нельзя бронировать на прошедшее время.")

    open_hour, close_hour = settings.BOOKING_OPEN_HOUR, settings.BOOKING_CLOSE_HOUR
    if (
        local_start.date() != local_end.date()
        or local_start.hour < open_hour
        or local_end.hour > close_hour
    ):
        raise BookingValidationError(
            f"Бронирование возможно только в рабочее время ({open_hour}:00-{close_hour}:00)."
        )


def create_booking(user, room, start, end):
    validate_interval(start, end)
    if not room.is_active:
        raise BookingValidationError("Эта переговорная недоступна для бронирования.")

    with transaction.atomic():
        # Блокируем строку комнаты: параллельные запросы на одну комнату выполняются по очереди,
        # поэтому двойное бронирование невозможно.
        Room.objects.select_for_update().get(pk=room.pk)
        conflict = Booking.objects.filter(
            room=room, status=Booking.Status.CONFIRMED, start__lt=end, end__gt=start
        ).first()
        if conflict:
            logger.warning(
                "Конфликт бронирования: user=%s room=%s %s-%s пересекается с booking=%s",
                user.username,
                room.id,
                start.isoformat(),
                end.isoformat(),
                conflict.id,
            )
            raise BookingConflict(
                "Переговорная уже занята на выбранное время.",
                details={
                    "conflicting_booking_id": conflict.id,
                    "start": conflict.start.isoformat(),
                    "end": conflict.end.isoformat(),
                },
            )
        booking = Booking.objects.create(user=user, room=room, start=start, end=end)

    logger.info(
        "Бронирование создано: id=%s user=%s room=%s %s-%s",
        booking.id,
        user.username,
        room.id,
        start.isoformat(),
        end.isoformat(),
    )
    return booking


def cancel_booking(user, booking):
    if booking.user_id != user.id and not is_admin(user):
        raise PermissionDeniedError("Нельзя отменить чужое бронирование.")
    if booking.status == Booking.Status.CANCELLED:
        raise BookingStateError("Бронирование уже отменено.")
    if booking.end <= timezone.now():
        raise BookingStateError("Нельзя отменить завершённое бронирование.")

    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
    logger.info("Бронирование отменено: id=%s user=%s", booking.id, user.username)
    return booking


def get_availability(room, day):
    """Занятость комнаты по часам на указанную дату (локальное время)."""
    open_hour, close_hour = settings.BOOKING_OPEN_HOUR, settings.BOOKING_CLOSE_HOUR
    day_start = timezone.make_aware(datetime.combine(day, time(open_hour)))
    day_end = timezone.make_aware(datetime.combine(day, time(close_hour)))
    bookings = list(
        Booking.objects.filter(
            room=room, status=Booking.Status.CONFIRMED, start__lt=day_end, end__gt=day_start
        )
    )
    slots = []
    for offset in range(close_hour - open_hour):
        slot_start = day_start + timedelta(hours=offset)
        slot_end = slot_start + timedelta(hours=1)
        busy_with = next((b for b in bookings if b.start < slot_end and b.end > slot_start), None)
        slots.append(
            {
                "hour": open_hour + offset,
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
                "busy": busy_with is not None,
                "booking_id": busy_with.id if busy_with else None,
            }
        )
    return slots
