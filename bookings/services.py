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
from .notifications import describe, notify, notify_admins

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

    conflict = booking = None
    with transaction.atomic():
        # Блокируем строку комнаты: параллельные запросы на одну комнату выполняются по очереди,
        # поэтому двойное бронирование невозможно.
        Room.objects.select_for_update().get(pk=room.pk)
        # Занятым считается время и подтверждённых, и ожидающих подтверждения броней.
        conflict = Booking.objects.filter(
            room=room, status__in=Booking.ACTIVE_STATUSES, start__lt=end, end__gt=start
        ).first()
        if conflict is None:
            status = Booking.Status.PENDING if room.is_vip else Booking.Status.CONFIRMED
            booking = Booking.objects.create(
                user=user, room=room, start=start, end=end, status=status
            )

    # Уведомления создаём вне блока atomic: иначе они откатились бы вместе с ошибкой.
    if conflict is not None:
        logger.warning(
            "Конфликт бронирования: user=%s room=%s %s-%s пересекается с booking=%s",
            user.username,
            room.id,
            start.isoformat(),
            end.isoformat(),
            conflict.id,
        )
        what = describe(room, start, end)
        notify(user, f"Не удалось забронировать {what}: время уже занято.")
        if conflict.user_id != user.id:
            notify(
                conflict.user,
                f"Попытка двойного бронирования: другой пользователь пытался забронировать "
                f"{what}, что пересекается с вашей бронью №{conflict.id}.",
            )
        raise BookingConflict(
            "Переговорная уже занята на выбранное время.",
            details={
                "conflicting_booking_id": conflict.id,
                "start": conflict.start.isoformat(),
                "end": conflict.end.isoformat(),
            },
        )

    logger.info(
        "Бронирование создано: id=%s user=%s room=%s status=%s %s-%s",
        booking.id,
        user.username,
        room.id,
        booking.status,
        start.isoformat(),
        end.isoformat(),
    )
    if booking.status == Booking.Status.PENDING:
        notify_admins(
            f"Новая заявка на VIP-комнату от {user.username}: {describe(room, start, end)}. "
            f"Требуется подтверждение.",
            exclude=user,
        )
    return booking


def cancel_booking(user, booking):
    if booking.user_id != user.id and not is_admin(user):
        raise PermissionDeniedError("Нельзя отменить чужое бронирование.")
    if booking.status == Booking.Status.CANCELLED:
        raise BookingStateError("Бронирование уже отменено.")
    if booking.status == Booking.Status.REJECTED:
        raise BookingStateError("Бронирование отклонено администратором, отменять нечего.")
    if booking.end <= timezone.now():
        raise BookingStateError("Нельзя отменить завершённое бронирование.")

    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.save(update_fields=["status", "cancelled_at"])
    logger.info("Бронирование отменено: id=%s user=%s", booking.id, user.username)
    return booking


def _decide(user, booking, new_status, check_future):
    if not is_admin(user):
        raise PermissionDeniedError("Подтверждать и отклонять брони могут только администраторы.")
    if booking.status != Booking.Status.PENDING:
        raise BookingStateError("Бронирование не ожидает подтверждения.")
    if check_future and booking.end <= timezone.now():
        raise BookingStateError("Время бронирования уже прошло, подтвердить нельзя.")
    booking.status = new_status
    booking.save(update_fields=["status"])


def approve_booking(user, booking):
    _decide(user, booking, Booking.Status.CONFIRMED, check_future=True)
    logger.info("Бронирование подтверждено: id=%s admin=%s", booking.id, user.username)
    what = describe(booking.room, booking.start, booking.end)
    notify(booking.user, f"Ваше бронирование {what} подтверждено администратором.")
    return booking


def reject_booking(user, booking):
    _decide(user, booking, Booking.Status.REJECTED, check_future=False)
    logger.info("Бронирование отклонено: id=%s admin=%s", booking.id, user.username)
    what = describe(booking.room, booking.start, booking.end)
    notify(booking.user, f"Ваше бронирование {what} отклонено администратором.")
    return booking


def get_availability(room, day):
    """Занятость комнаты по часам на указанную дату (локальное время)."""
    open_hour, close_hour = settings.BOOKING_OPEN_HOUR, settings.BOOKING_CLOSE_HOUR
    day_start = timezone.make_aware(datetime.combine(day, time(open_hour)))
    day_end = timezone.make_aware(datetime.combine(day, time(close_hour)))
    bookings = list(
        Booking.objects.filter(
            room=room, status__in=Booking.ACTIVE_STATUSES, start__lt=day_end, end__gt=day_start
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
                "pending": busy_with is not None and busy_with.status == Booking.Status.PENDING,
            }
        )
    return slots
