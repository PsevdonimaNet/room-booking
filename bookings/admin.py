from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Booking, Notification, Profile, Role, Room

User = get_user_model()


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "capacity", "location", "is_vip", "is_active")
    list_filter = ("is_active", "is_vip")
    search_fields = ("name", "location")


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "user", "start", "end", "status")
    list_filter = ("status", "room")
    date_hierarchy = "start"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "text", "created_at", "is_read")
    list_filter = ("is_read",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]

    def get_inline_instances(self, request, obj=None):
        # Профиль создаётся автоматически сигналом, при создании пользователя инлайн не нужен.
        return super().get_inline_instances(request, obj) if obj else []


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
