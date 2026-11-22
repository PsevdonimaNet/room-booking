from django.apps import AppConfig


class BookingsConfig(AppConfig):
    name = "bookings"
    verbose_name = "Бронирование"

    def ready(self):
        from . import signals  # noqa: F401
