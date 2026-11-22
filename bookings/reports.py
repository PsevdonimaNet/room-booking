import csv
from datetime import datetime, time, timedelta

from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date

from .exceptions import BookingValidationError
from .models import Booking

CSV_HEADERS = ["ID", "Комната", "Пользователь", "Начало", "Конец", "Часов", "Статус", "Создано"]


def parse_filters(params):
    """Разбирает и проверяет фильтры отчёта: date_from, date_to, room, status."""
    filters = {}
    for key in ("date_from", "date_to"):
        raw = params.get(key)
        if not raw:
            continue
        try:
            parsed = parse_date(raw)
        except ValueError:
            parsed = None
        if parsed is None:
            raise BookingValidationError(f"Неверная дата в параметре {key}. Формат: YYYY-MM-DD.")
        filters[key] = parsed
    if (
        "date_from" in filters
        and "date_to" in filters
        and filters["date_from"] > filters["date_to"]
    ):
        raise BookingValidationError("Дата «с» не может быть позже даты «по».")

    room = params.get("room")
    if room:
        if not room.isdigit():
            raise BookingValidationError("Параметр room должен быть числом.")
        filters["room"] = int(room)

    status = params.get("status")
    if status:
        if status not in Booking.Status.values:
            raise BookingValidationError("Неизвестный статус бронирования.")
        filters["status"] = status
    return filters


def filter_bookings(queryset, filters):
    """Применяет фильтры к бронированиям (по дате начала, в локальном часовом поясе)."""
    if "date_from" in filters:
        bound = timezone.make_aware(datetime.combine(filters["date_from"], time.min))
        queryset = queryset.filter(start__gte=bound)
    if "date_to" in filters:
        next_day = filters["date_to"] + timedelta(days=1)
        bound = timezone.make_aware(datetime.combine(next_day, time.min))
        queryset = queryset.filter(start__lt=bound)
    if "room" in filters:
        queryset = queryset.filter(room_id=filters["room"])
    if "status" in filters:
        queryset = queryset.filter(status=filters["status"])
    return queryset.order_by("start")


def _hours(booking):
    return (booking.end - booking.start).total_seconds() / 3600


def build_summary(queryset):
    """Сводка по комнатам: число броней по статусам и часы подтверждённых броней."""
    rows = {}
    for booking in queryset:
        row = rows.setdefault(
            booking.room_id,
            {
                "room": booking.room.name,
                "total": 0,
                "hours": 0,
                **dict.fromkeys(Booking.Status.values, 0),
            },
        )
        row["total"] += 1
        row[booking.status] += 1
        if booking.status == Booking.Status.CONFIRMED:
            row["hours"] += int(_hours(booking))
    return sorted(rows.values(), key=lambda row: row["room"])


def _safe(value):
    """Защита от CSV-инъекций: ячейки, начинающиеся со спецсимволов, экранируются."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _fmt(moment):
    return timezone.localtime(moment).strftime("%d.%m.%Y %H:%M")


def csv_response(queryset, filename="bookings.csv"):
    """CSV для Excel: кодировка UTF-8 с BOM, разделитель - точка с запятой."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(CSV_HEADERS)
    for booking in queryset.select_related("room", "user"):
        writer.writerow(
            [
                booking.id,
                _safe(booking.room.name),
                _safe(booking.user.username),
                _fmt(booking.start),
                _fmt(booking.end),
                f"{_hours(booking):g}",
                booking.get_status_display(),
                _fmt(booking.created_at),
            ]
        )
    return response
