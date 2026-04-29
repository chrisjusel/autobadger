from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from autobedge.models import DailyScheduleSnapshot, SchedulerSettings
from autobedge.scheduler import SchedulerManager


class DummyUserManager:
    pass


class DummyStorageManager:
    def __init__(self) -> None:
        self.saved_settings: SchedulerSettings | None = None

    def load_scheduler_settings(self) -> SchedulerSettings | None:
        return None

    def load_holidays(self) -> list[str] | None:
        return []

    def save_scheduler_settings(self, settings: SchedulerSettings) -> bool:
        self.saved_settings = settings
        return True


class DummyCoremApiManager:
    pass


class DummyNotificationManager:
    pass


class DummyNtpManager:
    def __init__(self, current_dt: datetime | None = None) -> None:
        self.tz = ZoneInfo("Europe/Rome")
        self._current_dt = current_dt or datetime(2026, 4, 29, 14, 33, tzinfo=self.tz)

    def local_datetime(self) -> datetime:
        return self._current_dt

    def get_current_date(self) -> str:
        return self._current_dt.strftime("%Y-%m-%d")


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

    def test_begin_suppresses_today_auto_plan_if_started_after_auto_time_and_startup_is_disabled(self) -> None:
        ntp_manager = DummyNtpManager(datetime(2026, 4, 29, 14, 34, tzinfo=ZoneInfo("Europe/Rome")))
        scheduler = SchedulerManager(
            DummyUserManager(),
            DummyStorageManager(),
            ntp_manager,
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:33")

        scheduler._initialize_auto_planning_state()

        self.assertEqual(scheduler._auto_planning_triggered_date, "2026-04-29")

    def test_begin_keeps_today_auto_plan_armed_if_started_before_auto_time_and_startup_is_disabled(self) -> None:
        ntp_manager = DummyNtpManager(datetime(2026, 4, 29, 14, 31, tzinfo=ZoneInfo("Europe/Rome")))
        scheduler = SchedulerManager(
            DummyUserManager(),
            DummyStorageManager(),
            ntp_manager,
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:33")

        scheduler._initialize_auto_planning_state()

        self.assertEqual(scheduler._auto_planning_triggered_date, "")

    def test_update_settings_rearms_today_auto_plan_if_startup_suppressed_it(self) -> None:
        storage = DummyStorageManager()
        ntp_manager = DummyNtpManager(datetime(2026, 4, 29, 14, 31, tzinfo=ZoneInfo("Europe/Rome")))
        scheduler = SchedulerManager(
            DummyUserManager(),
            storage,
            ntp_manager,
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="07:00")
        scheduler._initialize_auto_planning_state()

        ok, message = scheduler.update_settings(SchedulerSettings(auto_startup_enabled=False, auto_time="14:33"))

        self.assertTrue(ok)
        self.assertEqual(message, "")
        self.assertEqual(scheduler._auto_planning_triggered_date, "")
        self.assertEqual(scheduler._startup_suppressed_auto_planning_date, "")
        self.assertIsNotNone(storage.saved_settings)

    def test_rearmed_auto_plan_becomes_due_at_new_time(self) -> None:
        storage = DummyStorageManager()
        ntp_manager = DummyNtpManager(datetime(2026, 4, 29, 14, 31, tzinfo=ZoneInfo("Europe/Rome")))
        scheduler = SchedulerManager(
            DummyUserManager(),
            storage,
            ntp_manager,
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="07:00")
        scheduler._initialize_auto_planning_state()
        scheduler.update_settings(SchedulerSettings(auto_startup_enabled=False, auto_time="14:33"))

        due = scheduler._should_auto_plan(datetime(2026, 4, 29, 14, 33, tzinfo=scheduler.ntp_manager.tz), "2026-04-29")

        self.assertTrue(due)

    def test_update_settings_rearms_today_auto_plan_even_with_existing_schedule(self) -> None:
        storage = DummyStorageManager()
        ntp_manager = DummyNtpManager(datetime(2026, 4, 29, 14, 31, tzinfo=ZoneInfo("Europe/Rome")))
        scheduler = SchedulerManager(
            DummyUserManager(),
            storage,
            ntp_manager,
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:20")
        scheduler._auto_planning_triggered_date = "2026-04-29"
        scheduler._schedules.append(DailyScheduleSnapshot(user_id=2, username="alice", date="2026-04-29"))

        ok, message = scheduler.update_settings(SchedulerSettings(auto_startup_enabled=False, auto_time="14:33"))

        self.assertTrue(ok)
        self.assertEqual(message, "")
        self.assertEqual(scheduler._auto_planning_triggered_date, "")
        self.assertEqual(scheduler._auto_planning_rearm_date, "2026-04-29")

    def test_rearmed_auto_plan_ignores_existing_schedule_once(self) -> None:
        storage = DummyStorageManager()
        ntp_manager = DummyNtpManager(datetime(2026, 4, 29, 14, 31, tzinfo=ZoneInfo("Europe/Rome")))
        scheduler = SchedulerManager(
            DummyUserManager(),
            storage,
            ntp_manager,
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:20")
        scheduler._auto_planning_triggered_date = "2026-04-29"
        scheduler._schedules.append(DailyScheduleSnapshot(user_id=2, username="alice", date="2026-04-29"))
        scheduler.update_settings(SchedulerSettings(auto_startup_enabled=False, auto_time="14:33"))

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
