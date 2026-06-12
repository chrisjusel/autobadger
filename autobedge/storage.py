from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import (
    BadgeLogEntry,
    DailyScheduleSnapshot,
    NtfySettings,
    SchedulerSettings,
    UserProfile,
)


class StorageManager:
    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)
        self._lock = threading.RLock()

    def begin(self) -> bool:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return True

    def load_users(self) -> list[UserProfile] | None:
        data = self._read_json("users.json")
        if not isinstance(data, list):
            return None
        return [self._user_from_dict(item) for item in data if isinstance(item, dict)]

    def save_users(self, users: list[UserProfile]) -> bool:
        return self._write_json("users.json", [self._user_to_dict(user) for user in users])

    def load_holidays(self) -> list[str] | None:
        data = self._read_json("holidays.json")
        if not isinstance(data, list):
            return None
        return [str(item) for item in data]

    def save_holidays(self, holidays: list[str]) -> bool:
        return self._write_json("holidays.json", holidays)

    def load_ntfy_settings(self) -> NtfySettings | None:
        data = self._read_json("ntfy.json")
        if not isinstance(data, dict):
            return None
        return NtfySettings(
            enabled=bool(data.get("enabled", False)),
            base_url=str(data.get("base_url") or "https://ntfy.sh"),
            topic=str(data.get("topic") or ""),
            access_token=str(data.get("access_token") or ""),
        )

    def save_ntfy_settings(self, settings: NtfySettings) -> bool:
        return self._write_json("ntfy.json", asdict(settings))

    def load_schedules(self) -> list[DailyScheduleSnapshot] | None:
        data = self._read_json("schedules.json")
        if not isinstance(data, list):
            return None
        return [self._schedule_from_dict(item) for item in data if isinstance(item, dict)]

    def save_schedules(self, schedules: list[DailyScheduleSnapshot]) -> bool:
        return self._write_json("schedules.json", [asdict(entry) for entry in schedules])

    def load_scheduler_settings(self) -> SchedulerSettings | None:
        data = self._read_json("scheduler.json")
        if not isinstance(data, dict):
            return None
        return SchedulerSettings(
            auto_startup_enabled=bool(data.get("auto_startup_enabled", data.get("auto_enabled", True))),
            auto_time=str(data.get("auto_time") or "07:00"),
            exact_badge_chance_percent=int(data.get("exact_badge_chance_percent", 50)),
            near_badge_offset_chance_percent=int(data.get("near_badge_offset_chance_percent", 50)),
        )

    def save_scheduler_settings(self, settings: SchedulerSettings) -> bool:
        return self._write_json("scheduler.json", asdict(settings))

    def _read_json(self, filename: str) -> Any:
        path = self.data_dir / filename
        with self._lock:
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None

    def _write_json(self, filename: str, data: Any) -> bool:
        path = self.data_dir / filename
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with self._lock:
            try:
                tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp_path.replace(path)
                return True
            except OSError:
                return False

    @staticmethod
    def _user_from_dict(data: dict[str, Any]) -> UserProfile:
        logs = [
            BadgeLogEntry(
                timestamp=str(item.get("timestamp") or ""),
                type=str(item.get("type") or ""),
                success=bool(item.get("success", False)),
                note=str(item.get("note") or ""),
            )
            for item in data.get("badge_log", [])
            if isinstance(item, dict)
        ]
        return UserProfile(
            id=int(data.get("id", 0) or 0),
            username=str(data.get("username") or ""),
            password_hash=str(data.get("password_hash") or ""),
            is_admin=bool(data.get("is_admin", False)),
            corem_username=str(data.get("corem_username") or ""),
            corem_password=str(data.get("corem_password") or ""),
            corem_user_id=int(data.get("corem_user_id", 0) or 0),
            jwt_token=str(data.get("jwt_token") or ""),
            refresh_token=str(data.get("refresh_token") or ""),
            ntfy_enabled=bool(data.get("ntfy_enabled", False)),
            ntfy_topic=str(data.get("ntfy_topic") or ""),
            home_lat=float(data.get("home_lat", 0.0) or 0.0),
            home_lon=float(data.get("home_lon", 0.0) or 0.0),
            home_accuracy=int(data.get("home_accuracy", 50) or 50),
            office_lat=float(data.get("office_lat", 0.0) or 0.0),
            office_lon=float(data.get("office_lon", 0.0) or 0.0),
            office_accuracy=int(data.get("office_accuracy", 50) or 50),
            office_days=[int(day) for day in data.get("office_days", [])],
            scheduled_pauses=[str(day) for day in data.get("scheduled_pauses", [])],
            badge_log=logs,
        )

    @staticmethod
    def _user_to_dict(user: UserProfile) -> dict[str, Any]:
        data = asdict(user)
        data["badge_log"] = [asdict(entry) for entry in user.badge_log]
        return data

    @staticmethod
    def _schedule_from_dict(data: dict[str, Any]) -> DailyScheduleSnapshot:
        return DailyScheduleSnapshot(
            user_id=int(data.get("user_id", 0) or 0),
            username=str(data.get("username") or ""),
            date=str(data.get("date") or ""),
            planned_at=str(data.get("planned_at") or ""),
            in_office=bool(data.get("in_office", False)),
            skip_badge_in=bool(data.get("skip_badge_in", True)),
            skip_badge_out=bool(data.get("skip_badge_out", True)),
            badge_in_executed=bool(data.get("badge_in_executed", False)),
            badge_out_executed=bool(data.get("badge_out_executed", False)),
            badge_in_at=float(data.get("badge_in_at", 0.0) or 0.0),
            badge_out_at=float(data.get("badge_out_at", 0.0) or 0.0),
            note=str(data.get("note") or ""),
        )
