from django.conf import settings
from django.db import models


class Role(models.Model):
    """Роль пользователя в системе: обычный пользователь или администратор."""

    USER = "user"
    ADMIN = "admin"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=50)

    class Meta:
        verbose_name = "Роль"
        verbose_name_plural = "Роли"

    def __str__(self):
        return self.name


class Profile(models.Model):
    """Профиль пользователя: связывает стандартного User с ролью."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="profiles")

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"

    def __str__(self):
        return f"{self.user} ({self.role})"


class Room(models.Model):
    name = models.CharField(max_length=100, unique=True)
    capacity = models.PositiveSmallIntegerField()
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Переговорная"
        verbose_name_plural = "Переговорные"

    def __str__(self):
        return self.name


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Подтверждено"
        CANCELLED = "cancelled", "Отменено"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings"
    )
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="bookings")
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CONFIRMED)
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-start"]
        verbose_name = "Бронирование"
        verbose_name_plural = "Бронирования"
        indexes = [models.Index(fields=["room", "start", "end"], name="booking_room_time_idx")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end__gt=models.F("start")),
                name="booking_end_after_start",
            )
        ]

    def __str__(self):
        return f"{self.room} {self.start:%d.%m.%Y %H:%M}-{self.end:%H:%M}"
