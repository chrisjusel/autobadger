from __future__ import annotations

import unittest

from autobedge.models import PlanningStatusSnapshot, UserProfile

try:
    import flask  # noqa: F401
except ModuleNotFoundError as exc:  # pragma: no cover
    raise unittest.SkipTest("Flask non installato nell'ambiente di test") from exc

from autobedge.web import WebServerManager


class FakeUserManager:
    def __init__(self, user: UserProfile) -> None:
        self.user = user

    def get_user_by_id(self, user_id: int) -> UserProfile | None:
        return self.user if user_id == self.user.id else None

    def authenticate(self, username: str, password: str) -> UserProfile | None:
        return self.user if username == self.user.username else None


class FakeSchedulerManager:
    def __init__(self, pending: bool) -> None:
        self.snapshot = PlanningStatusSnapshot(pending=pending, success=False, message="Pianificazione automatica in corso", timestamp="2026-04-29T14:33:00+0200")

    def get_planning_status(self) -> PlanningStatusSnapshot:
        return self.snapshot


class FakeNtpManager:
    def get_current_date(self) -> str:
        return "2026-04-29"


class FakeNotificationManager:
    pass


class FakeCoremApiManager:
    pass


class WebPendingPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = UserProfile(id=2, username="alice")
        self.web = WebServerManager(
            FakeUserManager(self.user),
            FakeNtpManager(),
            FakeSchedulerManager(pending=True),
            FakeNotificationManager(),
            FakeCoremApiManager(),
            dry_run=True,
        )
        self.app = self.web.create_app()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = self.user.id

    def test_authenticated_pages_show_pending_overlay_when_planning_is_running(self) -> None:
        response = self.client.get("/settings")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Aggiornamento pianificazioni", response.data)
        self.assertIn(b"Pianificazione automatica in corso", response.data)

    def test_planning_status_endpoint_remains_available_during_pending_state(self) -> None:
        response = self.client.get("/api/planning-status")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.is_json)
        self.assertEqual(
            response.get_json(),
            {
                "pending": True,
                "success": False,
                "message": "Pianificazione automatica in corso",
                "timestamp": "2026-04-29T14:33:00+0200",
            },
        )


if __name__ == "__main__":
    unittest.main()
