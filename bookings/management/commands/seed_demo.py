from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from bookings.exceptions import DomainError
from bookings.models import Booking, Notification, Profile, Role, Room
from bookings.services import create_booking

User = get_user_model()

ROOMS = [
    ("Альфа", 6, "2 этаж, левое крыло", "Маркерная доска и телевизор.", False),
    ("Бета", 4, "2 этаж, правое крыло", "Тихая комната для небольших встреч.", False),
    ("Гамма", 10, "3 этаж, к. 301", "Проектор и система видеосвязи.", False),
    ("Конференц-зал", 20, "4 этаж", "Большой зал, бронь подтверждает администратор.", True),
]
DEMO_USERS = ["ivan", "maria", "petr"]
# (комната, пользователь, час начала, длительность)
PLAN = [("Альфа", "ivan", 9, 2), ("Бета", "maria", 11, 1), ("Гамма", "petr", 14, 3)]


class Command(BaseCommand):
    help = "Создаёт демо-данные: комнаты, пользователей и брони (запуск можно повторять)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="demo12345", help="Пароль демо-пользователей")
        parser.add_argument(
            "--load-users", type=int, default=0, help="Создать N пользователей load1..loadN"
        )
        parser.add_argument(
            "--clean-load",
            action="store_true",
            help="Удалить брони и уведомления load-пользователей",
        )

    def handle(self, *args, **options):
        if options["clean_load"]:
            self.clean_load()
            return

        password = options["password"]
        for name, capacity, location, description, is_vip in ROOMS:
            Room.objects.get_or_create(
                name=name,
                defaults={
                    "capacity": capacity,
                    "location": location,
                    "description": description,
                    "is_vip": is_vip,
                },
            )

        users = {name: self.ensure_user(name, password) for name in DEMO_USERS}
        manager = self.ensure_user("manager", password)
        Profile.objects.update_or_create(
            user=manager, defaults={"role": Role.objects.get(code=Role.ADMIN)}
        )
        for number in range(1, options["load_users"] + 1):
            self.ensure_user(f"load{number}", password)

        created = 0
        for offset in range(1, 6):
            day = timezone.localdate() + timedelta(days=offset)
            for room_name, username, hour, length in PLAN:
                start = timezone.make_aware(datetime.combine(day, time(hour)))
                try:
                    create_booking(
                        users[username],
                        Room.objects.get(name=room_name),
                        start,
                        start + timedelta(hours=length),
                    )
                    created += 1
                except DomainError:
                    continue  # такая бронь уже есть

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: комнат {Room.objects.count()}, пользователей {User.objects.count()}, "
                f"новых броней {created}. Пароль демо-пользователей: {password}"
            )
        )

    def ensure_user(self, username, password):
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.save()
        return user

    def clean_load(self):
        users = User.objects.filter(username__startswith="load")
        bookings, _ = Booking.objects.filter(user__in=users).delete()
        notifications, _ = Notification.objects.filter(user__in=users).delete()
        self.stdout.write(
            self.style.SUCCESS(f"Удалено броней: {bookings}, уведомлений: {notifications}")
        )
