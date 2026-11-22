from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .exceptions import (
    BookingConflict,
    BookingStateError,
    BookingValidationError,
    PermissionDeniedError,
)
from .models import Booking, Role, Room
from .services import cancel_booking, create_booking, get_availability, is_admin

User = get_user_model()


def slot(start_hour, length=1, days=1):
    """Интервал на завтра (по умолчанию): начало в start_hour, длительность length часов."""
    day = timezone.localdate() + timedelta(days=days)
    start = timezone.make_aware(datetime.combine(day, time(start_hour)))
    return start, start + timedelta(hours=length)


class BaseTestCase(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pass12345")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pass12345")
        self.admin = User.objects.create_superuser("boss", "boss@example.com", "pass12345")
        self.room = Room.objects.create(name="Альфа", capacity=6)


class RoleTests(BaseTestCase):
    def test_profiles_and_roles_created(self):
        self.assertEqual(self.alice.profile.role.code, Role.USER)
        self.assertEqual(self.admin.profile.role.code, Role.ADMIN)

    def test_is_admin(self):
        self.assertFalse(is_admin(self.alice))
        self.assertTrue(is_admin(self.admin))
        self.bob.profile.role = Role.objects.get(code=Role.ADMIN)
        self.bob.profile.save()
        self.assertTrue(is_admin(User.objects.get(pk=self.bob.pk)))


class BookingServiceTests(BaseTestCase):
    def test_create_booking(self):
        start, end = slot(10, 2)
        booking = create_booking(self.alice, self.room, start, end)
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(booking.user, self.alice)

    def test_overlap_is_conflict(self):
        create_booking(self.alice, self.room, *slot(10, 2))
        with self.assertRaises(BookingConflict) as ctx:
            create_booking(self.bob, self.room, *slot(11, 2))
        self.assertIn("conflicting_booking_id", ctx.exception.details)

    def test_adjacent_bookings_allowed(self):
        create_booking(self.alice, self.room, *slot(10, 2))
        create_booking(self.bob, self.room, *slot(12, 2))
        self.assertEqual(Booking.objects.count(), 2)

    def test_same_time_other_room_allowed(self):
        other = Room.objects.create(name="Бета", capacity=4)
        create_booking(self.alice, self.room, *slot(10, 2))
        create_booking(self.bob, other, *slot(10, 2))
        self.assertEqual(Booking.objects.count(), 2)

    def test_cancelled_booking_frees_slot(self):
        booking = create_booking(self.alice, self.room, *slot(10, 2))
        cancel_booking(self.alice, booking)
        create_booking(self.bob, self.room, *slot(10, 2))
        self.assertEqual(Booking.objects.filter(status=Booking.Status.CONFIRMED).count(), 1)

    def test_duration_limits(self):
        with self.assertRaises(BookingValidationError):
            create_booking(self.alice, self.room, *slot(9, 5))
        create_booking(self.alice, self.room, *slot(9, 4))

    def test_end_before_start(self):
        start, end = slot(10, 2)
        with self.assertRaises(BookingValidationError):
            create_booking(self.alice, self.room, end, start)

    def test_only_whole_hours(self):
        start, end = slot(10, 2)
        with self.assertRaises(BookingValidationError):
            create_booking(self.alice, self.room, start + timedelta(minutes=30), end)

    def test_past_is_rejected(self):
        with self.assertRaises(BookingValidationError):
            create_booking(self.alice, self.room, *slot(10, 1, days=-1))

    def test_outside_working_hours(self):
        with self.assertRaises(BookingValidationError):
            create_booking(self.alice, self.room, *slot(7, 1))
        with self.assertRaises(BookingValidationError):
            create_booking(self.alice, self.room, *slot(19, 2))

    def test_inactive_room(self):
        self.room.is_active = False
        self.room.save()
        with self.assertRaises(BookingValidationError):
            create_booking(self.alice, self.room, *slot(10, 1))

    def test_cancel_permissions(self):
        booking = create_booking(self.alice, self.room, *slot(10, 1))
        with self.assertRaises(PermissionDeniedError):
            cancel_booking(self.bob, booking)
        cancel_booking(self.admin, booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertIsNotNone(booking.cancelled_at)

    def test_cancel_twice(self):
        booking = create_booking(self.alice, self.room, *slot(10, 1))
        cancel_booking(self.alice, booking)
        with self.assertRaises(BookingStateError):
            cancel_booking(self.alice, booking)

    def test_cannot_cancel_finished(self):
        start, end = slot(10, 1, days=-1)
        booking = Booking.objects.create(user=self.alice, room=self.room, start=start, end=end)
        with self.assertRaises(BookingStateError):
            cancel_booking(self.alice, booking)

    def test_availability(self):
        start, end = slot(10, 2)
        booking = create_booking(self.alice, self.room, start, end)
        slots = get_availability(self.room, timezone.localtime(start).date())
        busy = [s["hour"] for s in slots if s["busy"]]
        self.assertEqual(busy, [10, 11])
        self.assertEqual(slots[2]["booking_id"], booking.id)


class ApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def payload(self, start_hour=10, length=2):
        start, end = slot(start_hour, length)
        return {"room": self.room.id, "start": start.isoformat(), "end": end.isoformat()}

    def test_auth_required(self):
        response = self.client.get("/api/rooms/")
        self.assertIn(response.status_code, (401, 403))

    def test_user_sees_only_active_rooms(self):
        Room.objects.create(name="Скрытая", capacity=2, is_active=False)
        self.client.force_authenticate(self.alice)
        response = self.client.get("/api/rooms/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["name"] for r in response.json()], ["Альфа"])

    def test_user_cannot_create_room(self):
        self.client.force_authenticate(self.alice)
        response = self.client.post("/api/rooms/", {"name": "Гамма", "capacity": 5}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_admin_room_crud(self):
        self.client.force_authenticate(self.admin)
        created = self.client.post("/api/rooms/", {"name": "Гамма", "capacity": 5}, format="json")
        self.assertEqual(created.status_code, 201)
        room_id = created.json()["id"]

        updated = self.client.patch(f"/api/rooms/{room_id}/", {"capacity": 8}, format="json")
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["capacity"], 8)

        deleted = self.client.delete(f"/api/rooms/{room_id}/")
        self.assertEqual(deleted.status_code, 204)
        self.assertFalse(Room.objects.get(pk=room_id).is_active)

    def test_room_validation(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post("/api/rooms/", {"name": "Ноль", "capacity": 0}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_booking(self):
        self.client.force_authenticate(self.alice)
        response = self.client.post("/api/bookings/", self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "confirmed")
        self.assertEqual(response.json()["user"], "alice")

    def test_conflict_returns_409(self):
        self.client.force_authenticate(self.alice)
        self.client.post("/api/bookings/", self.payload(10, 2), format="json")
        self.client.force_authenticate(self.bob)
        response = self.client.post("/api/bookings/", self.payload(11, 2), format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "booking_conflict")

    def test_validation_error_returns_400(self):
        self.client.force_authenticate(self.alice)
        response = self.client.post("/api/bookings/", self.payload(9, 5), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_missing_fields_return_400(self):
        self.client.force_authenticate(self.alice)
        response = self.client.post("/api/bookings/", {"room": self.room.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_history_is_scoped(self):
        self.client.force_authenticate(self.alice)
        self.client.post("/api/bookings/", self.payload(), format="json")
        self.assertEqual(len(self.client.get("/api/bookings/").json()), 1)

        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.get("/api/bookings/").json(), [])

        self.client.force_authenticate(self.admin)
        self.assertEqual(len(self.client.get("/api/bookings/").json()), 1)

    def test_history_room_filter(self):
        self.client.force_authenticate(self.alice)
        self.client.post("/api/bookings/", self.payload(), format="json")
        self.assertEqual(len(self.client.get(f"/api/bookings/?room={self.room.id}").json()), 1)
        self.assertEqual(self.client.get("/api/bookings/?room=999999").json(), [])
        self.assertEqual(self.client.get("/api/bookings/?room=abc").status_code, 400)

    def test_cancel_booking(self):
        self.client.force_authenticate(self.alice)
        booking_id = self.client.post("/api/bookings/", self.payload(), format="json").json()["id"]

        self.client.force_authenticate(self.bob)
        self.assertEqual(self.client.post(f"/api/bookings/{booking_id}/cancel/").status_code, 404)

        self.client.force_authenticate(self.alice)
        response = self.client.post(f"/api/bookings/{booking_id}/cancel/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

        again = self.client.post(f"/api/bookings/{booking_id}/cancel/")
        self.assertEqual(again.status_code, 409)

    def test_availability_endpoint(self):
        start, _ = slot(10, 2)
        create_booking(self.alice, self.room, *slot(10, 2))
        self.client.force_authenticate(self.bob)
        day = timezone.localtime(start).date().isoformat()
        response = self.client.get(f"/api/rooms/{self.room.id}/availability/?date={day}")
        self.assertEqual(response.status_code, 200)
        busy = [s["hour"] for s in response.json()["slots"] if s["busy"]]
        self.assertEqual(busy, [10, 11])

    def test_availability_bad_date(self):
        self.client.force_authenticate(self.bob)
        response = self.client.get(f"/api/rooms/{self.room.id}/availability/?date=not-a-date")
        self.assertEqual(response.status_code, 400)

    def test_api_docs_available(self):
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.get("/api/schema/").status_code, 200)
