from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .models import Notification, Role


def describe(room, start, end):
    """Короткое описание брони для текста уведомлений."""
    s, e = timezone.localtime(start), timezone.localtime(end)
    return f"«{room.name}», {s:%d.%m.%Y} {s:%H:%M}-{e:%H:%M}"


def notify(user, text):
    return Notification.objects.create(user=user, text=text[:300])


def notify_admins(text, exclude=None):
    admins = get_user_model().objects.filter(
        Q(is_superuser=True) | Q(profile__role__code=Role.ADMIN)
    )
    if exclude is not None:
        admins = admins.exclude(pk=exclude.pk)
    Notification.objects.bulk_create(
        [Notification(user=admin, text=text[:300]) for admin in admins.distinct()]
    )
