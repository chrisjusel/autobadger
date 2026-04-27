from __future__ import annotations

import random
import threading
import time
from dataclasses import replace
from datetime import datetime

from .corem_api import CoremApiManager
from .models import DailyScheduleSnapshot, PlanningStatusSnapshot, SchedulerSettings, UserProfile
from .notification_manager import NotificationManager
from .storage import StorageManager
from .time_manager import NTPManager
from .user_manager import UserManager


class SchedulerManager:
    POLL_SECONDS = 30

    def __init__(
        self,
        user_manager: UserManager,
        storage: StorageManager,
        ntp_manager: NTPManager,
        corem_api: CoremApiManager,
        notification_manager: NotificationManager,
        dry_run: bool,
    ) -> None:
        self.user_manager = user_manager
        self.storage = storage
        self.ntp_manager = ntp_manager
        self.corem_api = corem_api
        self.notification_manager = notification_manager
        self.dry_run = dry_run
        self._lock = threading.RLock()
        self._last_holiday_refresh_month_key = -1
        self._settings = SchedulerSettings()
        self._startup_planning_handled = False
        self._auto_planning_triggered_date = ""
        self._planning_status = PlanningStatusSnapshot()
        self._holidays: list[str] = []
        self._schedules: list[DailyScheduleSnapshot] = []
        self._pending_request: tuple[str, int] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def begin(self) -> None:
        self._settings = self.storage.load_scheduler_settings() or SchedulerSettings()
        self._holidays = self.storage.load_holidays() or []
        self._thread = threading.Thread(target=self._task_loop, name="autobedge-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def get_planned_date(self) -> str:
        dates = self.get_planned_dates_snapshot()
        return dates[0] if dates else ""

    def get_planned_dates_snapshot(self) -> list[str]:
        with self._lock:
            return sorted({entry.date for entry in self._schedules if entry.date})

    def get_schedules_snapshot(self, date: str = "") -> list[DailyScheduleSnapshot]:
        with self._lock:
            rows = self._schedules if not date else [entry for entry in self._schedules if entry.date == date]
            return [replace(entry) for entry in rows]

    def get_holidays_snapshot(self) -> list[str]:
        with self._lock:
            return list(self._holidays)

    def get_planning_status(self) -> PlanningStatusSnapshot:
        with self._lock:
            return replace(self._planning_status)

    def get_settings(self) -> SchedulerSettings:
        with self._lock:
            return replace(self._settings)

    def update_settings(self, settings: SchedulerSettings) -> tuple[bool, str]:
        settings.auto_time = settings.auto_time.strip()
        if not self._is_valid_time_value(settings.auto_time):
            return False, "Orario scheduler non valido. Usa il formato HH:MM."
        if not (0 <= settings.exact_badge_chance_percent <= 100 and 0 <= settings.near_badge_offset_chance_percent <= 100):
            return False, "Percentuali randomizzazione non valide. Usa valori tra 0 e 100."
        if not self.storage.save_scheduler_settings(settings):
            return False, "Impossibile salvare la configurazione scheduler."
        with self._lock:
            self._settings = settings
        return True, ""

    def trigger_planning_now(self) -> tuple[bool, str]:
        return self.trigger_planning_for_date(self.ntp_manager.get_current_date(), 0)

    def trigger_planning_for_date(self, date: str, user_id: int) -> tuple[bool, str]:
        valid, message = self._validate_planning_request(date, user_id)
        if not valid:
            return False, message
        with self._lock:
            self._pending_request = (date, user_id)
            self._planning_status = PlanningStatusSnapshot(True, False, f"Pianificazione in corso per {self._format_display_date(date)}.", self.ntp_manager.get_current_timestamp())
        return True, "Pianificazione messa in coda."

    def cancel_planning_for_date(self, date: str, user_id: int) -> tuple[bool, str]:
        if not date:
            return False, "Data non valida."
        with self._lock:
            before = len(self._schedules)
            self._schedules = [entry for entry in self._schedules if not (entry.date == date and (user_id <= 0 or entry.user_id == user_id))]
            removed = before - len(self._schedules)
        if removed == 0:
            return False, f"Nessuna pianificazione trovata per {self._format_display_date(date)}."
        if user_id > 0:
            user = self.user_manager.get_user_by_id(user_id)
            if user:
                return True, f"Pianificazione rimossa per {self._format_display_date(date)} ({user.username})."
        return True, f"Pianificazione rimossa per {self._format_display_date(date)}."

    def skip_remaining_today_for_user(self, user_id: int) -> tuple[bool, str]:
        current_date = self.ntp_manager.get_current_date()
        now_epoch = self.ntp_manager.now()
        user = self.user_manager.get_user_by_id(user_id)
        if not user or user.is_admin:
            return False, "Utente non valido."
        skipped_in = 0
        skipped_out = 0
        reason = "Cancellato manualmente dall'utente per oggi"
        with self._lock:
            for entry in self._schedules:
                if entry.user_id != user_id or entry.date != current_date:
                    continue
                if not entry.badge_in_executed and not entry.skip_badge_in and entry.badge_in_at > now_epoch:
                    entry.skip_badge_in = True
                    entry.note = self._join_notes(entry.note, reason)
                    skipped_in += 1
                if not entry.badge_out_executed and not entry.skip_badge_out and entry.badge_out_at > now_epoch:
                    entry.skip_badge_out = True
                    entry.note = self._join_notes(entry.note, reason)
                    skipped_out += 1
        if skipped_in == 0 and skipped_out == 0:
            return False, "Nessuna pianificazione futura di oggi da cancellare."
        return True, f"Pianificazioni residue di oggi messe in skip (IN: {skipped_in}, OUT: {skipped_out})."

    def _task_loop(self) -> None:
        while not self._stop.is_set():
            self.ntp_manager.maintain()
            now_dt = self.ntp_manager.local_datetime()
            current_date = now_dt.strftime("%Y-%m-%d")
            self._purge_past_schedules(current_date)
            startup_due = self._should_auto_plan_at_startup(current_date)
            daily_due = not startup_due and self._should_auto_plan(now_dt, current_date)
            self._refresh_holidays_if_needed(now_dt)
            if startup_due or daily_due:
                self._set_planning_status(True, False, f"Pianificazione automatica in corso per {self._format_display_date(current_date)}.")
                ok, message = self._execute_planning_for_date(current_date, 0)
                self._auto_planning_triggered_date = current_date if ok else self._auto_planning_triggered_date
                self._set_planning_status(False, ok, message)
            self._process_pending_planning_requests()
            self._execute_due_badges(self.ntp_manager.now())
            self._stop.wait(self.POLL_SECONDS)

    def _process_pending_planning_requests(self) -> None:
        with self._lock:
            request = self._pending_request
            self._pending_request = None
        if request is None:
            return
        ok, message = self._execute_planning_for_date(request[0], request[1])
        self._set_planning_status(False, ok, message)

    def _validate_planning_request(self, date: str, user_id: int) -> tuple[bool, str]:
        if len(date) != 10:
            return False, "Data non valida."
        current_date = self.ntp_manager.get_current_date()
        if not current_date:
            return False, "Data corrente non disponibile."
        if date < current_date:
            return False, "Non e' possibile pianificare una data passata."
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            return False, "Data non valida."
        if user_id > 0:
            user = self.user_manager.get_user_by_id(user_id)
            if not user or user.is_admin:
                return False, "Utente non valido per la pianificazione."
        return True, ""

    def _execute_planning_for_date(self, date: str, user_id: int) -> tuple[bool, str]:
        valid, message = self._validate_planning_request(date, user_id)
        if not valid:
            return False, message
        target_dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=self.ntp_manager.tz)
        self._clear_plan_for_date(date, user_id)
        self._refresh_holidays_if_needed(target_dt, force_refresh=True)
        return self._plan_date(target_dt, date, self.ntp_manager.now(), user_id)

    def _plan_date(self, timeinfo: datetime, date: str, now_epoch: float, user_id: int) -> tuple[bool, str]:
        planned_at = self.ntp_manager.get_current_timestamp()
        weekend = timeinfo.weekday() >= 5
        holiday = date in self._holidays
        settings = self.get_settings()
        closed_note = ""
        if weekend and holiday:
            closed_note = "Giornata non lavorativa: weekend e festivita'"
        elif weekend:
            closed_note = "Giornata non lavorativa: weekend"
        elif holiday:
            closed_note = "Giornata non lavorativa: festivita'"
        users = self.user_manager.get_corem_enabled_users()
        if user_id > 0:
            users = [user for user in users if user.id == user_id]
        new_schedules: list[DailyScheduleSnapshot] = []
        for user in users:
            if date in user.scheduled_pauses:
                continue
            if closed_note:
                policy_skip_in = True
                policy_skip_out = True
                policy_in = -1
                policy_out = -1
                note = closed_note
            else:
                ok, policy, error = self.corem_api.fetch_daily_policy(user, date)
                if not ok:
                    return False, f"Pianificazione non completata per {self._format_display_date(date)}: errore Corem per {user.username} ({error})."
                policy_skip_in = policy.skip_badge_in
                policy_skip_out = policy.skip_badge_out
                policy_in = policy.badge_in_minutes
                policy_out = policy.badge_out_minutes
                note = policy.note
            badge_in_base = policy_in if policy_in >= 0 else 9 * 60
            badge_out_base = policy_out if policy_out >= 0 else 18 * 60
            exact_in = policy_in >= 0 or self._chance(settings.exact_badge_chance_percent)
            exact_out = policy_out >= 0 or self._chance(settings.exact_badge_chance_percent)
            in_offset = 0 if exact_in else self._random_badge_offset(settings.near_badge_offset_chance_percent)
            out_offset = 0 if exact_out else self._random_badge_offset(settings.near_badge_offset_chance_percent)
            in_second = 0 if policy_in >= 0 else random.randrange(60)
            out_second = 0 if policy_out >= 0 else random.randrange(60)
            entry = DailyScheduleSnapshot(
                user_id=user.id,
                username=user.username,
                date=date,
                planned_at=planned_at,
                in_office=self._is_office_day(user, timeinfo),
                skip_badge_in=policy_skip_in,
                skip_badge_out=policy_skip_out,
                note=note,
                badge_in_at=self._make_local_epoch(date, badge_in_base + in_offset, in_second),
                badge_out_at=self._make_local_epoch(date, badge_out_base + out_offset, out_second),
            )
            if not closed_note:
                if now_epoch > entry.badge_in_at:
                    entry.skip_badge_in = True
                    entry.note = self._join_notes(entry.note, "Avvio tardivo: badge IN saltato")
                if now_epoch > entry.badge_out_at:
                    entry.skip_badge_out = True
                    entry.note = self._join_notes(entry.note, "Avvio tardivo: badge OUT saltato")
            new_schedules.append(entry)
        with self._lock:
            self._schedules.extend(new_schedules)
        suffix = ", tutte in skip" if closed_note else ""
        if user_id > 0:
            user = self.user_manager.get_user_by_id(user_id)
            username = f" ({user.username}, " if user else " ("
            return True, f"Pianificazione aggiornata per {self._format_display_date(date)}{username}{len(new_schedules)} righe{suffix})."
        return True, f"Pianificazione aggiornata per {self._format_display_date(date)} ({len(new_schedules)} righe{suffix})."

    def _execute_due_badges(self, now_epoch: float) -> None:
        with self._lock:
            snapshot = [replace(entry) for entry in self._schedules]
        for entry in snapshot:
            if not entry.skip_badge_in and not entry.badge_in_executed and now_epoch >= entry.badge_in_at:
                self._execute_badge(entry, "IN")
            if not entry.skip_badge_out and not entry.badge_out_executed and now_epoch >= entry.badge_out_at:
                self._execute_badge(entry, "OUT")

    def _execute_badge(self, entry: DailyScheduleSnapshot, type_: str) -> None:
        user = self.user_manager.get_user_by_id(entry.user_id)
        if user is None:
            return
        if self.dry_run:
            ok, note = True, "DRY RUN"
        else:
            ok, note = self.corem_api.submit_badge(user, entry.in_office, type_)
        if not ok:
            return
        timestamp = self.ntp_manager.get_current_timestamp()
        self.user_manager.append_badge_log(entry.user_id, type_, True, note, timestamp)
        self.notification_manager.send_badge_notification(user, entry.in_office, type_, note, timestamp, self.dry_run)
        with self._lock:
            for stored in self._schedules:
                if stored.user_id == entry.user_id and stored.date == entry.date:
                    if type_ == "IN":
                        stored.badge_in_executed = True
                    else:
                        stored.badge_out_executed = True
                    break

    def _refresh_holidays_if_needed(self, timeinfo: datetime, force_refresh: bool = False) -> None:
        month_key = timeinfo.year * 100 + timeinfo.month
        if not force_refresh and month_key == self._last_holiday_refresh_month_key:
            return
        if not force_refresh and timeinfo.day != 1 and self._holidays:
            return
        users = self.user_manager.get_corem_enabled_users()
        if not users:
            return
        ok, holidays, _ = self.corem_api.fetch_holidays(users[0])
        if ok:
            with self._lock:
                self._holidays = holidays
                self._last_holiday_refresh_month_key = month_key
            self.storage.save_holidays(holidays)

    def _purge_past_schedules(self, current_date: str) -> None:
        with self._lock:
            self._schedules = [entry for entry in self._schedules if not entry.date or entry.date >= current_date]

    def _clear_plan_for_date(self, date: str, user_id: int = 0) -> None:
        with self._lock:
            self._schedules = [entry for entry in self._schedules if not (entry.date == date and (user_id <= 0 or entry.user_id == user_id))]

    def _set_planning_status(self, pending: bool, success: bool, message: str) -> None:
        with self._lock:
            self._planning_status = PlanningStatusSnapshot(pending, success, message, self.ntp_manager.get_current_timestamp())

    def _should_auto_plan_at_startup(self, current_date: str) -> bool:
        if self._startup_planning_handled or not current_date:
            return False
        self._startup_planning_handled = True
        settings = self.get_settings()
        return settings.auto_startup_enabled and not self._has_schedule_for_date(current_date)

    def _should_auto_plan(self, timeinfo: datetime, current_date: str) -> bool:
        settings = self.get_settings()
        if not self._is_valid_time_value(settings.auto_time):
            return False
        scheduled_hour, scheduled_minute = [int(part) for part in settings.auto_time.split(":")]
        current_minutes = timeinfo.hour * 60 + timeinfo.minute
        scheduled_minutes = scheduled_hour * 60 + scheduled_minute
        return current_minutes >= scheduled_minutes and self._auto_planning_triggered_date != current_date and not self._has_schedule_for_date(current_date)

    def _has_schedule_for_date(self, date: str) -> bool:
        with self._lock:
            return any(entry.date == date for entry in self._schedules)

    def _is_office_day(self, user: UserProfile, timeinfo: datetime) -> bool:
        day = timeinfo.weekday()
        return 0 <= day <= 4 and day in user.office_days

    def _make_local_epoch(self, date: str, minutes: int, second: int) -> float:
        hour, minute = divmod(minutes, 60)
        scheduled = datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, minute=minute, second=second, tzinfo=self.ntp_manager.tz)
        return scheduled.timestamp()

    @staticmethod
    def _join_notes(first: str, second: str) -> str:
        return second if not first else first if not second else f"{first} | {second}"

    @staticmethod
    def _is_valid_time_value(value: str) -> bool:
        try:
            datetime.strptime(value, "%H:%M")
            return len(value) == 5
        except ValueError:
            return False

    @staticmethod
    def _chance(percent: int) -> bool:
        return random.randrange(100) < percent

    @staticmethod
    def _random_badge_offset(near_chance_percent: int) -> int:
        if SchedulerManager._chance(near_chance_percent):
            return random.randint(-3, 3)
        return random.choice([-5, -4, 4, 5])

    @staticmethod
    def _format_display_date(date: str) -> str:
        return f"{date[8:10]}/{date[5:7]}/{date[0:4]}" if len(date) == 10 and date[4] == "-" and date[7] == "-" else date

