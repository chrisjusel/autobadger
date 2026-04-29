from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from autobedge.models import SchedulerSettings
from autobedge.scheduler import SchedulerManager


class DummyUserManager:
    pass


class DummyStorageManager:
    pass


class DummyCoremApiManager:
    pass


class DummyNotificationManager:
    pass


class DummyNtpManager:
    def __init__(self) -> None:
        self.tz = ZoneInfo("Europe/Rome")


class SchedulerManagerAutoPlanTests(unittest.TestCase):
    def test_auto_plan_uses_auto_time_even_when_startup_flag_is_disabled(self) -> None:
        scheduler = SchedulerManager(
            DummyUserManager(),
            DummyStorageManager(),
            DummyNtpManager(),
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:33")

        due = scheduler._should_auto_plan(datetime(2026, 4, 29, 14, 33, tzinfo=scheduler.ntp_manager.tz), "2026-04-29")

        self.assertTrue(due)

    def test_auto_plan_does_not_run_twice_for_same_day(self) -> None:
        scheduler = SchedulerManager(
            DummyUserManager(),
            DummyStorageManager(),
            DummyNtpManager(),
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:33")
        scheduler._auto_planning_triggered_date = "2026-04-29"

        due = scheduler._should_auto_plan(datetime(2026, 4, 29, 14, 34, tzinfo=scheduler.ntp_manager.tz), "2026-04-29")

        self.assertFalse(due)


if __name__ == "__main__":
    unittest.main()
