from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from bookings.models import Booking, Room
from bookings.services import create_booking, is_admin
from bookings.tests import slot

User = get_user_model()


class MetricsTests(TestCase):
    def test_metrics_endpoint(self):
        self.client.get("/health/")
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("django_http", response.content.decode("utf-8"))

    def test_metrics_not_logged(self):
        with self.assertNoLogs("requests", level="INFO"):
            self.client.get("/metrics")

    def test_regular_requests_are_logged(self):
        with self.assertLogs("requests", level="INFO"):
            self.client.get("/health/")

    def test_internal_host_allowed(self):
        response = self.client.get("/health/", HTTP_HOST="web:8000")
        self.assertEqual(response.status_code, 200)


class SeedDemoTests(TestCase):
    def test_seed_is_idempotent(self):
        call_command("seed_demo", "--load-users", "3", verbosity=0)
        self.assertEqual(Room.objects.count(), 4)
        self.assertTrue(Room.objects.get(name="Конференц-зал").is_vip)
        self.assertTrue(User.objects.filter(username="load3").exists())
        self.assertTrue(is_admin(User.objects.get(username="manager")))
        bookings = Booking.objects.count()
        self.assertGreater(bookings, 0)

        call_command("seed_demo", "--load-users", "3", verbosity=0)
        self.assertEqual(Booking.objects.count(), bookings)
        self.assertEqual(Room.objects.count(), 4)

    def test_demo_user_can_login(self):
        call_command("seed_demo", verbosity=0)
        self.assertTrue(self.client.login(username="ivan", password="demo12345"))

    def test_clean_load_removes_only_load_data(self):
        call_command("seed_demo", "--load-users", "2", verbosity=0)
        before = Booking.objects.exclude(user__username__startswith="load").count()
        room = Room.objects.get(name="Альфа")
        create_booking(User.objects.get(username="load1"), room, *slot(12, 1, days=30))
        self.assertTrue(Booking.objects.filter(user__username="load1").exists())

        call_command("seed_demo", "--clean-load", verbosity=0)
        self.assertFalse(Booking.objects.filter(user__username__startswith="load").exists())
        self.assertEqual(Booking.objects.count(), before)
