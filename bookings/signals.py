from django.contrib.auth import get_user_model
from django.db.models.signals import post_migrate, post_save
from django.dispatch import receiver

from .models import Profile, Role

ROLE_NAMES = {Role.USER: "Пользователь", Role.ADMIN: "Администратор"}


def ensure_profile(user):
    """Гарантирует, что у пользователя есть профиль с ролью."""
    code = Role.ADMIN if user.is_superuser else Role.USER
    role, _ = Role.objects.get_or_create(code=code, defaults={"name": ROLE_NAMES[code]})
    Profile.objects.get_or_create(user=user, defaults={"role": role})


@receiver(post_save, sender=get_user_model())
def create_profile(sender, instance, created, **kwargs):
    if created:
        ensure_profile(instance)


@receiver(post_migrate)
def create_default_roles(sender, **kwargs):
    """После миграций создаёт роли и профили для уже существующих пользователей."""
    if sender.label != "bookings":
        return
    for code, name in ROLE_NAMES.items():
        Role.objects.get_or_create(code=code, defaults={"name": name})
    for user in get_user_model().objects.filter(profile__isnull=True):
        ensure_profile(user)
