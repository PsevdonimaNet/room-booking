from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/signup/", views.signup, name="signup"),
    path("rooms/", views.rooms, name="rooms"),
    path("rooms/<int:pk>/", views.room_detail, name="room_detail"),
    path("rooms/<int:pk>/book/", views.book_room, name="book_room"),
    path("bookings/", views.history, name="history"),
    path("bookings/<int:pk>/cancel/", views.cancel, name="cancel_booking"),
    path("manage/rooms/", views.manage_rooms, name="manage_rooms"),
    path("manage/rooms/new/", views.room_form, name="room_create"),
    path("manage/rooms/<int:pk>/edit/", views.room_form, name="room_edit"),
    path("notifications/", views.notifications, name="notifications"),
    path("manage/pending/", views.pending, name="pending"),
    path("manage/bookings/<int:pk>/approve/", views.approve, name="approve_booking"),
    path("manage/bookings/<int:pk>/reject/", views.reject, name="reject_booking"),
    path("manage/report/", views.report, name="report"),
    path("manage/report/csv/", views.report_csv, name="report_csv"),
    path("manage/users/", views.manage_users, name="manage_users"),
    path("manage/users/<int:pk>/role/", views.set_role, name="set_role"),
]
