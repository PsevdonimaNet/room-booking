from bookings.models import Booking
from bookings.services import is_admin


def user_role(request):
    """Данные для меню: роль, число непрочитанных уведомлений и заявок на подтверждение."""
    user = request.user
    context = {"is_admin": is_admin(user), "unread_count": 0, "pending_count": 0}
    if user.is_authenticated:
        context["unread_count"] = user.notifications.filter(is_read=False).count()
        if context["is_admin"]:
            context["pending_count"] = Booking.objects.filter(status=Booking.Status.PENDING).count()
    return context
