from rest_framework.permissions import SAFE_METHODS, BasePermission

from .services import is_admin


class IsAdminOrReadOnly(BasePermission):
    """Читать могут все авторизованные, изменять - только администраторы."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return is_admin(request.user)
