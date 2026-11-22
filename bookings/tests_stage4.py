from datetime import timedelta

from django.http import QueryDict
from django.utils import timezone
from rest_framework.test import APIClient

from .exceptions import (
    BookingConflict,
    BookingStateError,
    BookingValidationError,
    PermissionDeniedError,
)
from .models import Booking, Notification, Room
from .reports import build_summary, csv_response, filter_bookings, parse_filters
from .services import (
    approve_booking,
    cancel_booking,
    create_booking,
    get_availability,
    reject_booking,
)
from .tests import BaseTestCase, slot


class VipBookingTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.vip = Room.objects.create(name="Зал", capacity=12, is_vip=True)

    def test_vip_booking_is_pending(self):
        booking = create_booking(self.alice, self.vip, *slot(10, 2))
        self.assertEqual(booking.status, Booking.Status.PENDING)

    def test_regular_booking_is_confirmed(self):
        booking = create_booking(self.alice, self.room, *slot(10, 2))
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

    def test_pending_blocks_slot(self):
        create_booking(self.alice, self.vip, *slot(10, 2))
        with self.assertRaises(BookingConflict):
            create_booking(self.bob, self.vip, *slot(11, 1))

    def test_availability_marks_pending(self):
        start, end = slot(10, 1)
        create_booking(self.alice, self.vip, start, end)
        slots = get_availability(self.vip, timezone.localtime(start).date())
        busy = [s for s in slots if s["busy"]]
        self.assertEqual(len(busy), 1)
        self.assertTrue(busy[0]["pending"])

    def test_admin_approves(self):
        booking = create_booking(self.alice, self.vip, *slot(10, 2))
        approve_booking(self.admin, booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)
        self.assertTrue(Notification.objects.filter(user=self.alice, text__contains="подтверждено"))

    def test_user_cannot_approve_or_reject(self):
        booking = create_booking(self.alice, self.vip, *slot(10, 2))
        with self.assertRaises(PermissionDeniedError):
            approve_booking(self.alice, booking)
        with self.assertRaises(PermissionDeniedError):
            reject_booking(self.bob, booking)

    def test_cannot_approve_twice(self):
        booking = create_booking(self.alice, self.vip, *slot(10, 2))
        approve_booking(self.admin, booking)
        with self.assertRaises(BookingStateError):
            approve_booking(self.admin, booking)

    def test_cannot_approve_past_booking(self):
        start, end = slot(10, 1, days=-1)
        booking = Booking.objects.create(
            user=self.alice, room=self.vip, start=start, end=end, status=Booking.Status.PENDING
        )
        with self.assertRaises(BookingStateError):
            approve_booking(self.admin, booking)

    def test_reject_frees_slot_and_notifies(self):
        booking = create_booking(self.alice, self.vip, *slot(10, 2))
        reject_booking(self.admin, booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.REJECTED)
        self.assertTrue(Notification.objects.filter(user=self.alice, text__contains="отклонено"))
        create_booking(self.bob, self.vip, *slot(10, 2))

    def test_cancel_pending_and_rejected(self):
        pending = create_booking(self.alice, self.vip, *slot(10, 1))
        cancel_booking(self.alice, pending)
        self.assertEqual(pending.status, Booking.Status.CANCELLED)

        other = create_booking(self.alice, self.vip, *slot(12, 1))
        reject_booking(self.admin, other)
        with self.assertRaises(BookingStateError):
            cancel_booking(self.alice, other)

    def test_admins_notified_about_request(self):
        create_booking(self.alice, self.vip, *slot(10, 1))
        self.assertTrue(Notification.objects.filter(user=self.admin, text__contains="заявка"))
        self.assertFalse(Notification.objects.filter(user=self.bob).exists())

    def test_admin_requesting_does_not_notify_himself(self):
        create_booking(self.admin, self.vip, *slot(10, 1))
        self.assertFalse(Notification.objects.filter(user=self.admin).exists())


class ConflictNotificationTests(BaseTestCase):
    def test_conflict_notifies_both_users(self):
        create_booking(self.alice, self.room, *slot(10, 2))
        with self.assertRaises(BookingConflict):
            create_booking(self.bob, self.room, *slot(11, 2))
        # Уведомления сохраняются, несмотря на исключение
        self.assertTrue(Notification.objects.filter(user=self.bob, text__contains="занято"))
        self.assertTrue(
            Notification.objects.filter(user=self.alice, text__contains="двойного бронирования")
        )

    def test_self_conflict_notifies_only_once(self):
        create_booking(self.alice, self.room, *slot(10, 2))
        with self.assertRaises(BookingConflict):
            create_booking(self.alice, self.room, *slot(11, 2))
        self.assertEqual(Notification.objects.filter(user=self.alice).count(), 1)


class ReportsTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.other = Room.objects.create(name="Бета", capacity=4)
        self.b1 = create_booking(self.alice, self.room, *slot(10, 2, days=1))
        self.b2 = create_booking(self.bob, self.other, *slot(10, 3, days=3))
        cancel_booking(self.bob, self.b2)

    def day(self, days):
        return (timezone.localdate() + timedelta(days=days)).isoformat()

    def filtered(self, **params):
        query = QueryDict(mutable=True)
        query.update(params)
        return filter_bookings(Booking.objects.all(), parse_filters(query))

    def test_no_filters_returns_all(self):
        self.assertEqual(self.filtered().count(), 2)

    def test_filter_by_date_range(self):
        self.assertEqual(list(self.filtered(date_from=self.day(2))), [self.b2])
        self.assertEqual(list(self.filtered(date_to=self.day(1))), [self.b1])
        rng = self.filtered(date_from=self.day(1), date_to=self.day(3))
        self.assertEqual(rng.count(), 2)

    def test_filter_by_room_and_status(self):
        self.assertEqual(list(self.filtered(room=str(self.room.id))), [self.b1])
        self.assertEqual(list(self.filtered(status="cancelled")), [self.b2])

    def test_invalid_filters(self):
        for params in (
            {"date_from": "abc"},
            {"date_from": "2026-13-45"},
            {"date_from": self.day(3), "date_to": self.day(1)},
            {"room": "x"},
            {"status": "unknown"},
        ):
            with self.assertRaises(BookingValidationError):
                parse_filters(self._qd(params))

    def _qd(self, params):
        query = QueryDict(mutable=True)
        query.update(params)
        return query

    def test_summary(self):
        summary = build_summary(Booking.objects.select_related("room"))
        rows = {row["room"]: row for row in summary}
        self.assertEqual(rows["Альфа"]["confirmed"], 1)
        self.assertEqual(rows["Альфа"]["hours"], 2)
        self.assertEqual(rows["Бета"]["cancelled"], 1)
        self.assertEqual(rows["Бета"]["hours"], 0)

    def test_csv_content(self):
        response = csv_response(Booking.objects.all())
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        text = response.content.decode("utf-8")
        self.assertTrue(text.startswith("\ufeffID;Комната;Пользователь"))
        self.assertIn("Альфа;alice", text)
        self.assertEqual(len(text.strip().splitlines()), 3)

    def test_csv_escapes_formulas(self):
        self.room.name = "=SUM(A1)"
        self.room.save()
        text = csv_response(Booking.objects.all()).content.decode("utf-8")
        self.assertIn("'=SUM(A1)", text)


class StageFourApiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.vip = Room.objects.create(name="Зал", capacity=12, is_vip=True)

    def payload(self, room, hour=10, length=2):
        start, end = slot(hour, length)
        return {"room": room.id, "start": start.isoformat(), "end": end.isoformat()}

    def test_room_exposes_is_vip(self):
        self.client.force_authenticate(self.alice)
        rooms = {r["name"]: r for r in self.client.get("/api/rooms/").json()}
        self.assertTrue(rooms["Зал"]["is_vip"])
        self.assertFalse(rooms["Альфа"]["is_vip"])

    def test_vip_flow_via_api(self):
        self.client.force_authenticate(self.alice)
        created = self.client.post("/api/bookings/", self.payload(self.vip), format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["status"], "pending")
        booking_id = created.json()["id"]

        denied = self.client.post(f"/api/bookings/{booking_id}/approve/")
        self.assertEqual(denied.status_code, 403)

        self.client.force_authenticate(self.admin)
        approved = self.client.post(f"/api/bookings/{booking_id}/approve/")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "confirmed")
        again = self.client.post(f"/api/bookings/{booking_id}/approve/")
        self.assertEqual(again.status_code, 409)

    def test_reject_via_api(self):
        self.client.force_authenticate(self.alice)
        booking_id = self.client.post(
            "/api/bookings/", self.payload(self.vip), format="json"
        ).json()["id"]
        self.client.force_authenticate(self.admin)
        response = self.client.post(f"/api/bookings/{booking_id}/reject/")
        self.assertEqual(response.json()["status"], "rejected")

    def test_status_filter(self):
        self.client.force_authenticate(self.alice)
        self.client.post("/api/bookings/", self.payload(self.vip, 10), format="json")
        self.client.post("/api/bookings/", self.payload(self.room, 14), format="json")
        pending = self.client.get("/api/bookings/?status=pending").json()
        self.assertEqual(len(pending), 1)
        self.assertEqual(self.client.get("/api/bookings/?status=oops").status_code, 400)

    def test_export_requires_admin(self):
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.get("/api/bookings/export/").status_code, 403)

    def test_export_csv(self):
        create_booking(self.alice, self.room, *slot(10, 2))
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/bookings/export/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("Альфа", response.content.decode("utf-8"))

    def test_export_filters(self):
        create_booking(self.alice, self.room, *slot(10, 2))
        self.client.force_authenticate(self.admin)
        day = (timezone.localdate() + timedelta(days=5)).isoformat()
        response = self.client.get(f"/api/bookings/export/?date_from={day}")
        self.assertEqual(len(response.content.decode("utf-8").strip().splitlines()), 1)
        self.assertEqual(self.client.get("/api/bookings/export/?date_from=bad").status_code, 400)
