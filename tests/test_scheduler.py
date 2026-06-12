from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from autobedge.models import DailyAttendancePolicy, DailyScheduleSnapshot, SchedulerSettings, UserProfile
from autobedge.scheduler import SchedulerManager
from autobedge.storage import StorageManager


class DummyUserManager:
    def __init__(self, users: list[UserProfile] | None = None) -> None:
        self._users = users or []

    def get_corem_enabled_users(self) -> list[UserProfile]:
        return list(self._users)

    def get_user_by_id(self, user_id: int) -> UserProfile | None:
        return next((user for user in self._users if user.id == user_id), None)


class DummyStorageManager:
    def __init__(self) -> None:
        self.saved_settings: SchedulerSettings | None = None
        self.saved_schedules: list[DailyScheduleSnapshot] | None = None

    def load_scheduler_settings(self) -> SchedulerSettings | None:
        return None

    def load_holidays(self) -> list[str] | None:
        return []

    def load_schedules(self) -> list[DailyScheduleSnapshot] | None:
        return None

    def save_scheduler_settings(self, settings: SchedulerSettings) -> bool:
        self.saved_settings = settings
        return True

    def save_holidays(self, holidays: list[str]) -> bool:
        return True

    def save_schedules(self, schedules: list[DailyScheduleSnapshot]) -> bool:
        self.saved_schedules = list(schedules)
        return True


class DummyCoremApiManager:
    def fetch_holidays(self, user: UserProfile) -> tuple[bool, list[str], str]:
        return True, [], ""

    def fetch_daily_policy(self, user: UserProfile, date: str) -> tuple[bool, DailyAttendancePolicy, str]:
        return True, DailyAttendancePolicy(), ""

    def submit_badge(self, user: UserProfile, in_office: bool, type_: str) -> tuple[bool, str]:
        return True, "DRY RUN"


class DummyNotificationManager:
    def send_badge_notification(self, user: UserProfile, in_office: bool, type_: str, note: str, timestamp: str, dry_run: bool) -> bool:
        return True


class DummyNtpManager:
    def __init__(self, current_dt: datetime | None = None) -> None:
        self.tz = ZoneInfo("Europe/Rome")
        self._current_dt = current_dt or datetime(2026, 4, 29, 14, 33, tzinfo=self.tz)

    def local_datetime(self) -> datetime:
        return self._current_dt

    def set_current_datetime(self, current_dt: datetime) -> None:
        self._current_dt = current_dt

    def get_current_date(self) -> str:
        return self._current_dt.strftime("%Y-%m-%d")

    def maintain(self) -> None:
        return None

    def now(self) -> float:
        return self._current_dt.timestamp()

    def get_current_timestamp(self) -> str:
        return self._current_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")


class SchedulerManagerAutoPlanTests(unittest.TestCase):
    @staticmethod
    def _corem_user() -> UserProfile:
        return UserProfile(
            id=2,
            username="alice",
            corem_username="alice",
            corem_password="secret",
            office_days=[0, 1, 2, 3, 4],
        )

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
        self.assertEqual(scheduler._auto_planning_triggered_key, "2026-04-29|14:33|50|50")

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
        self.assertEqual(scheduler._auto_planning_triggered_key, "2026-04-29|07:00|50|50")
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
        self.assertEqual(scheduler._auto_planning_triggered_date, "2026-04-29")
        self.assertEqual(scheduler._auto_planning_triggered_key, "")

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
        scheduler._auto_planning_triggered_key = "2026-04-29|14:20|50|50"
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
        scheduler._auto_planning_triggered_key = "2026-04-29|14:33|50|50"

        due = scheduler._should_auto_plan(datetime(2026, 4, 29, 14, 34, tzinfo=scheduler.ntp_manager.tz), "2026-04-29")

        self.assertFalse(due)

    def test_scheduler_tick_creates_first_automatic_plan_at_configured_time(self) -> None:
        ntp_manager = DummyNtpManager(datetime(2026, 4, 29, 14, 33, tzinfo=ZoneInfo("Europe/Rome")))
        scheduler = SchedulerManager(
            DummyUserManager([self._corem_user()]),
            DummyStorageManager(),
            ntp_manager,
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:33")
        scheduler._startup_planning_handled = True

        scheduler._run_scheduler_tick()

        schedules = scheduler.get_schedules_snapshot("2026-04-29")
        self.assertEqual(len(schedules), 1)
        self.assertEqual(scheduler._auto_planning_triggered_date, "2026-04-29")
        self.assertFalse(scheduler.get_planning_status().pending)
        self.assertTrue(scheduler.get_planning_status().success)

    def test_scheduler_tick_recreates_automatic_plan_after_same_day_time_change(self) -> None:
        ntp_manager = DummyNtpManager(datetime(2026, 4, 29, 14, 33, tzinfo=ZoneInfo("Europe/Rome")))
        scheduler = SchedulerManager(
            DummyUserManager([self._corem_user()]),
            DummyStorageManager(),
            ntp_manager,
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:33")
        scheduler._startup_planning_handled = True

        scheduler._run_scheduler_tick()
        first_schedule = scheduler.get_schedules_snapshot("2026-04-29")[0]

        ntp_manager.set_current_datetime(datetime(2026, 4, 29, 14, 34, tzinfo=ZoneInfo("Europe/Rome")))
        ok, message = scheduler.update_settings(SchedulerSettings(auto_startup_enabled=False, auto_time="14:34"))

        self.assertTrue(ok)
        self.assertEqual(message, "")
        self.assertEqual(scheduler._auto_planning_triggered_key, "2026-04-29|14:33|50|50")

        scheduler._run_scheduler_tick()
        second_schedule = scheduler.get_schedules_snapshot("2026-04-29")[0]

        self.assertEqual(len(scheduler.get_schedules_snapshot("2026-04-29")), 1)
        self.assertEqual(scheduler._auto_planning_triggered_date, "2026-04-29")
        self.assertEqual(scheduler._auto_planning_triggered_key, "2026-04-29|14:34|50|50")
        self.assertNotEqual(first_schedule.planned_at, second_schedule.planned_at)


class SchedulerPersistenceTests(unittest.TestCase):
    def test_storage_round_trip_preserves_schedule_fields(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            storage = StorageManager(data_dir)
            storage.begin()
            entry = DailyScheduleSnapshot(
                user_id=2,
                username="alice",
                date="2099-12-31",
                planned_at="2099-12-30T07:00:00+0000",
                in_office=True,
                skip_badge_in=False,
                skip_badge_out=False,
                badge_in_executed=True,
                badge_out_executed=False,
                badge_in_at=1234.5,
                badge_out_at=6789.0,
                note="Permesso orario in uscita",
            )

            self.assertTrue(storage.save_schedules([entry]))
            loaded = storage.load_schedules()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0], entry)

    def test_plan_date_persists_schedules(self) -> None:
        storage = DummyStorageManager()
        scheduler = SchedulerManager(
            DummyUserManager([SchedulerManagerAutoPlanTests._corem_user()]),
            storage,
            DummyNtpManager(),
            DummyCoremApiManager(),
            DummyNotificationManager(),
            dry_run=True,
        )
        scheduler._settings = SchedulerSettings(auto_startup_enabled=False, auto_time="14:33")

        scheduler._execute_planning_for_date("2026-04-29", 0)

        self.assertIsNotNone(storage.saved_schedules)
        self.assertEqual(len(storage.saved_schedules), 1)
        self.assertEqual(storage.saved_schedules[0].username, "alice")

    def test_begin_restores_future_schedules_and_drops_past(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            storage = StorageManager(data_dir)
            storage.begin()
            storage.save_schedules(
                [
                    DailyScheduleSnapshot(user_id=2, username="alice", date="2026-04-29"),
                    DailyScheduleSnapshot(user_id=2, username="alice", date="2020-01-01"),
                    DailyScheduleSnapshot(user_id=2, username="alice", date="2099-12-31"),
                ]
            )
            scheduler = SchedulerManager(
                DummyUserManager(),
                storage,
                DummyNtpManager(),
                DummyCoremApiManager(),
                DummyNotificationManager(),
                dry_run=True,
            )

            try:
                scheduler.begin()
                dates = scheduler.get_planned_dates_snapshot()
            finally:
                scheduler.stop()

            self.assertIn("2026-04-29", dates)
            self.assertIn("2099-12-31", dates)
            self.assertNotIn("2020-01-01", dates)


if __name__ == "__main__":
    unittest.main()
