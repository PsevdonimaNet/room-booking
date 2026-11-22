import logging
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from bookings.exceptions import DomainError
from bookings.models import Booking, Profile, Role, Room
from bookings.reports import build_summary, csv_response, filter_bookings, parse_filters
from bookings.services import (
    approve_booking,
    cancel_booking,
    create_booking,
    get_availability,
    is_admin,
    reject_booking,
)

from .forms import BookingForm, RoomForm

logger = logging.getLogger("web")
User = get_user_model()


def admin_required(view):
    """Доступ только для администраторов (остальным - 403, анонимным - страница входа)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied("Требуются права администратора.")
        return view(request, *args, **kwargs)

    return login_required(wrapper)


def _visible_rooms(user):
    rooms = Room.objects.all()
    return rooms if is_admin(user) else rooms.filter(is_active=True)


def _parse_day(value):
    try:
        return parse_date(value or "") or timezone.localdate()
    except ValueError:
        return timezone.localdate()


def _room_url(room, day):
    return f"{reverse('room_detail', args=[room.pk])}?date={day.isoformat()}"


def home(request):
    return redirect("rooms")


def signup(request):
    if request.user.is_authenticated:
        return redirect("rooms")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        logger.info("Зарегистрирован новый пользователь: %s", user.username)
        return redirect("rooms")
    return render(request, "registration/signup.html", {"form": form})


@login_required
def rooms(request):
    return render(request, "rooms.html", {"rooms": _visible_rooms(request.user)})


@login_required
def room_detail(request, pk):
    room = get_object_or_404(_visible_rooms(request.user), pk=pk)
    day = _parse_day(request.GET.get("date"))
    context = {
        "room": room,
        "day": day,
        "prev_day": day - timedelta(days=1),
        "next_day": day + timedelta(days=1),
        "slots": get_availability(room, day),
        "form": BookingForm(initial={"date": day}),
    }
    return render(request, "room_detail.html", context)


@login_required
@require_POST
def book_room(request, pk):
    room = get_object_or_404(_visible_rooms(request.user), pk=pk)
    form = BookingForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Проверьте поля формы: дата, время начала и длительность.")
        return redirect("room_detail", pk=room.pk)

    day = form.cleaned_data["date"]
    start, end = form.interval()
    try:
        booking = create_booking(request.user, room, start, end)
    except DomainError as error:
        messages.error(request, error.message)
        return redirect(_room_url(room, day))

    if booking.status == Booking.Status.PENDING:
        messages.success(
            request,
            f"Заявка на «{room.name}» отправлена и ожидает подтверждения администратором.",
        )
    else:
        messages.success(request, f"Переговорная «{room.name}» забронирована.")
    return redirect("history")


@login_required
def history(request):
    bookings = Booking.objects.select_related("room", "user")
    if not is_admin(request.user):
        bookings = bookings.filter(user=request.user)
    return render(request, "history.html", {"bookings": bookings, "now": timezone.now()})


@login_required
@require_POST
def cancel(request, pk):
    bookings = Booking.objects.all()
    if not is_admin(request.user):
        bookings = bookings.filter(user=request.user)
    booking = get_object_or_404(bookings, pk=pk)
    try:
        cancel_booking(request.user, booking)
    except DomainError as error:
        messages.error(request, error.message)
    else:
        messages.success(request, "Бронирование отменено.")
    return redirect("history")


@admin_required
def manage_rooms(request):
    return render(request, "manage_rooms.html", {"rooms": Room.objects.all()})


@admin_required
def room_form(request, pk=None):
    room = get_object_or_404(Room, pk=pk) if pk else None
    form = RoomForm(request.POST or None, instance=room)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        logger.info(
            "Комната %s: id=%s by=%s", "изменена" if room else "создана", saved.id, request.user
        )
        messages.success(request, f"Переговорная «{saved.name}» сохранена.")
        return redirect("manage_rooms")
    return render(request, "room_form.html", {"form": form, "room": room})


@admin_required
def manage_users(request):
    users = User.objects.select_related("profile__role").order_by("username")
    return render(request, "manage_users.html", {"users": users, "roles": Role.objects.all()})


@admin_required
@require_POST
def set_role(request, pk):
    user = get_object_or_404(User, pk=pk)
    role = get_object_or_404(Role, code=request.POST.get("role"))
    if user == request.user:
        messages.error(request, "Нельзя менять роль самому себе.")
    else:
        Profile.objects.update_or_create(user=user, defaults={"role": role})
        logger.info("Роль изменена: user=%s role=%s by=%s", user.username, role.code, request.user)
        messages.success(request, f"Пользователю {user.username} назначена роль «{role.name}».")
    return redirect("manage_users")


@login_required
def notifications(request):
    items = list(request.user.notifications.all()[:50])
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return render(request, "notifications.html", {"items": items})


@admin_required
def pending(request):
    bookings = (
        Booking.objects.filter(status=Booking.Status.PENDING)
        .select_related("room", "user")
        .order_by("start")
    )
    return render(request, "pending.html", {"bookings": bookings})


def _decide(request, pk, action, success_text):
    booking = get_object_or_404(Booking.objects.select_related("room", "user"), pk=pk)
    try:
        action(request.user, booking)
    except DomainError as error:
        messages.error(request, error.message)
    else:
        messages.success(request, success_text)
    return redirect("pending")


@admin_required
@require_POST
def approve(request, pk):
    return _decide(request, pk, approve_booking, "Бронирование подтверждено.")


@admin_required
@require_POST
def reject(request, pk):
    return _decide(request, pk, reject_booking, "Бронирование отклонено.")


@admin_required
def report(request):
    summary, bookings = [], []
    try:
        filters = parse_filters(request.GET)
        queryset = filter_bookings(Booking.objects.select_related("room", "user"), filters)
        summary = build_summary(queryset)
        bookings = list(queryset[:100])
    except DomainError as error:
        messages.error(request, error.message)
    context = {
        "summary": summary,
        "total": sum(row["total"] for row in summary),
        "bookings": bookings,
        "rooms": Room.objects.all(),
        "statuses": Booking.Status.choices,
        "values": request.GET,
        "query": request.GET.urlencode(),
    }
    return render(request, "report.html", context)


@admin_required
def report_csv(request):
    try:
        filters = parse_filters(request.GET)
    except DomainError as error:
        messages.error(request, error.message)
        return redirect("report")
    queryset = filter_bookings(Booking.objects.all(), filters)
    logger.info("Экспорт CSV из веб-интерфейса: by=%s filters=%s", request.user, filters)
    return csv_response(queryset)
