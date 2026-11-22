from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.utils import OperationalError
from django.test import TestCase

from bookings.models import Room

from . import db_guard
from .middleware import _username

User = get_user_model()


class BrokenRequest:
    """Запрос, у которого получение пользователя завершается ошибкой БД."""

    @property
    def user(self):
        raise OperationalError("down")


class DbGuardTests(TestCase):
    def setUp(self):
        db_guard.reset()
        self.addCleanup(db_guard.reset)

    def test_breaker_state(self):
        self.assertFalse(db_guard.is_open())
        db_guard.mark_failure()
        self.assertTrue(db_guard.is_open())
        db_guard.reset()
        self.assertFalse(db_guard.is_open())

    def test_open_breaker_fails_fast(self):
        db_guard.mark_failure()
        response = self.client.get("/rooms/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertEqual(response["Retry-After"], "5")

    def test_health_and_metrics_are_exempt(self):
        db_guard.mark_failure()
        self.assertEqual(self.client.get("/metrics").status_code, 200)
        self.assertEqual(self.client.get("/health/").status_code, 200)
        # успешная проверка здоровья закрывает защиту
        self.assertFalse(db_guard.is_open())

    def test_web_view_db_error_returns_503(self):
        user = User.objects.create_user("web", password="pass12345")
        self.client.force_login(user)
        with patch("web.views._visible_rooms", side_effect=OperationalError("down")):
            response = self.client.get("/rooms/")
        self.assertEqual(response.status_code, 503)
        self.assertTrue(db_guard.is_open())

    def test_api_db_error_returns_503(self):
        user = User.objects.create_user("api", password="pass12345")
        room = Room.objects.create(name="Альфа", capacity=4)
        self.client.force_login(user)
        with patch("bookings.views.get_availability", side_effect=OperationalError("down")):
            response = self.client.get(f"/api/rooms/{room.id}/availability/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "service_unavailable")
        self.assertTrue(db_guard.is_open())

    def test_health_reports_database_failure(self):
        with patch("core.views.connection") as fake_connection:
            fake_connection.cursor.side_effect = OperationalError("down")
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["checks"]["database"], "error")
        self.assertTrue(db_guard.is_open())

    def test_username_does_not_crash_when_db_down(self):
        self.assertEqual(_username(BrokenRequest()), "unknown")
        self.assertTrue(db_guard.is_open())
        # при открытой защите к БД не обращаемся вовсе
        self.assertEqual(_username(BrokenRequest()), "unknown")
