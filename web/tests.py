from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from bookings.models import Booking, Role, Room
from bookings.services import create_booking

User = get_user_model()


def tomorrow_slot(start_hour, length=1):
    day = timezone.localdate() + timedelta(days=1)
    start = timezone.make_aware(datetime.combine(day, time(start_hour)))
    return day, start, start + timedelta(hours=length)


class WebTestCase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pass12345")
        self.bob = User.objects.create_user("bob", password="pass12345")
        self.admin = User.objects.create_superuser("boss", password="pass12345")
        self.room = Room.objects.create(name="Альфа", capacity=6, location="2 этаж")

    def book(self, day, hour="10", duration="2"):
        return self.client.post(
            f"/rooms/{self.room.id}/book/",
            {"date": day.isoformat(), "start_hour": hour, "duration": duration},
            follow=True,
        )


class AuthPagesTests(WebTestCase):
    def test_anonymous_redirected_to_login(self):
        response = self.client.get("/rooms/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_login_page_and_login(self):
        self.assertEqual(self.client.get("/accounts/login/").status_code, 200)
        response = self.client.post(
            "/accounts/login/", {"username": "alice", "password": "pass12345"}
        )
        self.assertEqual(response.status_code, 302)

    def test_signup_creates_user_with_role(self):
        response = self.client.post(
            "/accounts/signup/",
            {
                "username": "newbie",
                "password1": "Str0ng-pass-2026",
                "password2": "Str0ng-pass-2026",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newbie")
        self.assertEqual(user.profile.role.code, Role.USER)

    def test_home_redirects(self):
        self.assertEqual(self.client.get("/").status_code, 302)


class RoomPagesTests(WebTestCase):
    def test_rooms_list(self):
        Room.objects.create(name="Скрытая", capacity=2, is_active=False)
        self.client.force_login(self.alice)
        response = self.client.get("/rooms/")
        self.assertContains(response, "Альфа")
        self.assertNotContains(response, "Скрытая")

    def test_room_detail_shows_busy_slots(self):
        day, start, end = tomorrow_slot(10, 2)
        create_booking(self.bob, self.room, start, end)
        self.client.force_login(self.alice)
        response = self.client.get(f"/rooms/{self.room.id}/?date={day.isoformat()}")
        self.assertContains(response, "занято", count=2)

    def test_room_detail_bad_date_falls_back(self):
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.get(f"/rooms/{self.room.id}/?date=2026-13-45").status_code, 200
        )
        self.assertEqual(self.client.get(f"/rooms/{self.room.id}/?date=abc").status_code, 200)

    def test_inactive_room_hidden_from_user(self):
        hidden = Room.objects.create(name="Скрытая", capacity=2, is_active=False)
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f"/rooms/{hidden.id}/").status_code, 404)


class BookingPagesTests(WebTestCase):
    def test_book_room_success(self):
        day, _, _ = tomorrow_slot(10)
        self.client.force_login(self.alice)
        response = self.book(day)
        self.assertContains(response, "забронирована")
        self.assertEqual(Booking.objects.filter(user=self.alice).count(), 1)

    def test_book_room_conflict_shows_message(self):
        day, start, end = tomorrow_slot(10, 2)
        create_booking(self.bob, self.room, start, end)
        self.client.force_login(self.alice)
        response = self.book(day, hour="11")
        self.assertContains(response, "занята")
        self.assertEqual(Booking.objects.count(), 1)

    def test_book_room_rule_violation_shows_message(self):
        day, _, _ = tomorrow_slot(10)
        self.client.force_login(self.alice)
        response = self.book(day, hour="19", duration="2")
        self.assertContains(response, "рабочее время")
        self.assertEqual(Booking.objects.count(), 0)

    def test_book_room_invalid_form(self):
        self.client.force_login(self.alice)
        response = self.client.post(f"/rooms/{self.room.id}/book/", {"date": "oops"}, follow=True)
        self.assertContains(response, "Проверьте поля")

    def test_book_requires_post(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f"/rooms/{self.room.id}/book/").status_code, 405)

    def test_history_is_scoped_to_user(self):
        _, start, end = tomorrow_slot(10)
        create_booking(self.alice, self.room, start, end)
        self.client.force_login(self.bob)
        self.assertContains(self.client.get("/bookings/"), "Бронирований пока нет")
        self.client.force_login(self.alice)
        self.assertContains(self.client.get("/bookings/"), "Альфа")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/bookings/"), "alice")

    def test_cancel_booking(self):
        _, start, end = tomorrow_slot(10)
        booking = create_booking(self.alice, self.room, start, end)
        self.client.force_login(self.alice)
        response = self.client.post(f"/bookings/{booking.id}/cancel/", follow=True)
        self.assertContains(response, "отменено")
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)

    def test_cancel_foreign_booking_not_found(self):
        _, start, end = tomorrow_slot(10)
        booking = create_booking(self.alice, self.room, start, end)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(f"/bookings/{booking.id}/cancel/").status_code, 404)

    def test_cancel_twice_shows_message(self):
        _, start, end = tomorrow_slot(10)
        booking = create_booking(self.alice, self.room, start, end)
        self.client.force_login(self.alice)
        self.client.post(f"/bookings/{booking.id}/cancel/")
        response = self.client.post(f"/bookings/{booking.id}/cancel/", follow=True)
        self.assertContains(response, "уже отменено")


class ManagePagesTests(WebTestCase):
    def test_non_admin_gets_403(self):
        self.client.force_login(self.alice)
        for url in ("/manage/rooms/", "/manage/rooms/new/", "/manage/users/"):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get("/manage/rooms/").status_code, 302)

    def test_admin_lists(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/manage/rooms/"), "Альфа")
        self.assertContains(self.client.get("/manage/users/"), "alice")

    def test_admin_creates_and_edits_room(self):
        self.client.force_login(self.admin)
        data = {
            "name": "Гамма",
            "capacity": 10,
            "location": "3 этаж",
            "description": "",
            "is_active": "on",
        }
        self.assertEqual(self.client.post("/manage/rooms/new/", data).status_code, 302)
        room = Room.objects.get(name="Гамма")
        data["capacity"] = 12
        self.assertEqual(self.client.post(f"/manage/rooms/{room.id}/edit/", data).status_code, 302)
        room.refresh_from_db()
        self.assertEqual(room.capacity, 12)

    def test_room_form_validation(self):
        self.client.force_login(self.admin)
        response = self.client.post("/manage/rooms/new/", {"name": "", "capacity": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Room.objects.count(), 1)

    def test_admin_changes_role(self):
        self.client.force_login(self.admin)
        response = self.client.post(f"/manage/users/{self.alice.id}/role/", {"role": "admin"})
        self.assertEqual(response.status_code, 302)
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.role.code, Role.ADMIN)

    def test_admin_cannot_change_own_role(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            f"/manage/users/{self.admin.id}/role/", {"role": "user"}, follow=True
        )
        self.assertContains(response, "Нельзя менять роль самому себе")
        self.admin.profile.refresh_from_db()
        self.assertEqual(self.admin.profile.role.code, Role.ADMIN)

    def test_user_cannot_change_roles(self):
        self.client.force_login(self.alice)
        response = self.client.post(f"/manage/users/{self.bob.id}/role/", {"role": "admin"})
        self.assertEqual(response.status_code, 403)
