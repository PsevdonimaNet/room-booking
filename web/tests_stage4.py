from bookings.models import Booking, Notification, Room
from bookings.services import create_booking

from .tests import WebTestCase, tomorrow_slot


class VipWebTests(WebTestCase):
    def setUp(self):
        super().setUp()
        self.vip = Room.objects.create(name="Зал", capacity=12, is_vip=True)

    def test_vip_badge_in_list(self):
        self.client.force_login(self.alice)
        self.assertContains(self.client.get("/rooms/"), "VIP")

    def test_vip_booking_waits_for_approval(self):
        day, _, _ = tomorrow_slot(10)
        self.client.force_login(self.alice)
        response = self.client.post(
            f"/rooms/{self.vip.id}/book/",
            {"date": day.isoformat(), "start_hour": "10", "duration": "2"},
            follow=True,
        )
        self.assertContains(response, "ожидает подтверждения")
        self.assertEqual(Booking.objects.get().status, Booking.Status.PENDING)

    def test_pending_page_access(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get("/manage/pending/").status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/manage/pending/").status_code, 200)

    def test_admin_approves_and_user_sees_notification(self):
        _, start, end = tomorrow_slot(10, 2)
        booking = create_booking(self.alice, self.vip, start, end)

        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/manage/pending/"), "alice")
        response = self.client.post(f"/manage/bookings/{booking.id}/approve/", follow=True)
        self.assertContains(response, "Бронирование подтверждено")
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

        self.client.force_login(self.alice)
        self.assertContains(self.client.get("/rooms/"), "Уведомления (1)")
        self.assertContains(self.client.get("/notifications/"), "подтверждено администратором")
        self.assertNotContains(self.client.get("/rooms/"), "Уведомления (")

    def test_admin_rejects(self):
        _, start, end = tomorrow_slot(10, 2)
        booking = create_booking(self.alice, self.vip, start, end)
        self.client.force_login(self.admin)
        self.client.post(f"/manage/bookings/{booking.id}/reject/")
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.REJECTED)

    def test_user_cannot_approve(self):
        _, start, end = tomorrow_slot(10, 2)
        booking = create_booking(self.alice, self.vip, start, end)
        self.client.force_login(self.alice)
        self.assertEqual(
            self.client.post(f"/manage/bookings/{booking.id}/approve/").status_code, 403
        )

    def test_room_form_saves_vip(self):
        self.client.force_login(self.admin)
        data = {"name": "Люкс", "capacity": 8, "is_vip": "on", "is_active": "on"}
        self.client.post("/manage/rooms/new/", data)
        self.assertTrue(Room.objects.get(name="Люкс").is_vip)


class ConflictNotificationWebTests(WebTestCase):
    def test_owner_sees_conflict_notification(self):
        day, start, end = tomorrow_slot(10, 2)
        create_booking(self.bob, self.room, start, end)
        self.client.force_login(self.alice)
        self.client.post(
            f"/rooms/{self.room.id}/book/",
            {"date": day.isoformat(), "start_hour": "11", "duration": "1"},
        )
        self.assertTrue(Notification.objects.filter(user=self.alice).exists())
        self.client.force_login(self.bob)
        self.assertContains(self.client.get("/notifications/"), "двойного бронирования")

    def test_empty_notifications(self):
        self.client.force_login(self.alice)
        self.assertContains(self.client.get("/notifications/"), "Уведомлений пока нет")


class ReportWebTests(WebTestCase):
    def setUp(self):
        super().setUp()
        _, start, end = tomorrow_slot(10, 2)
        create_booking(self.alice, self.room, start, end)

    def test_report_access(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get("/manage/report/").status_code, 403)
        self.assertEqual(self.client.get("/manage/report/csv/").status_code, 403)

    def test_report_page(self):
        self.client.force_login(self.admin)
        response = self.client.get("/manage/report/")
        self.assertContains(response, "Сводка по комнатам")
        self.assertContains(response, "Альфа")

    def test_report_with_filters(self):
        self.client.force_login(self.admin)
        response = self.client.get(f"/manage/report/?room={self.room.id}&status=confirmed")
        self.assertContains(response, "alice")
        empty = self.client.get("/manage/report/?status=cancelled")
        self.assertContains(empty, "Нет данных")

    def test_report_bad_filter_shows_error(self):
        self.client.force_login(self.admin)
        response = self.client.get("/manage/report/?date_from=oops")
        self.assertContains(response, "Неверная дата")

    def test_csv_download(self):
        self.client.force_login(self.admin)
        response = self.client.get("/manage/report/csv/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("Альфа", response.content.decode("utf-8"))

    def test_csv_bad_filter_redirects(self):
        self.client.force_login(self.admin)
        response = self.client.get("/manage/report/csv/?date_from=oops")
        self.assertEqual(response.status_code, 302)
