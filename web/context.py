from bookings.services import is_admin


def user_role(request):
    """Добавляет в шаблоны флаг is_admin (для меню и кнопок администратора)."""
    return {"is_admin": is_admin(request.user)}
