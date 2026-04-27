from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BadgeLogEntry:
    timestamp: str = ""
    type: str = ""
    success: bool = False
    note: str = ""


@dataclass
class UserProfile:
    id: int = 0
    username: str = ""
    password_hash: str = ""
    is_admin: bool = False
    corem_username: str = ""
    corem_password: str = ""
    corem_user_id: int = 0
    jwt_token: str = ""
    refresh_token: str = ""
    ntfy_enabled: bool = False
    ntfy_topic: str = ""
    home_lat: float = 0.0
    home_lon: float = 0.0
    home_accuracy: int = 50
    office_lat: float = 0.0
    office_lon: float = 0.0
    office_accuracy: int = 50
    office_days: list[int] = field(default_factory=list)
    scheduled_pauses: list[str] = field(default_factory=list)
    badge_log: list[BadgeLogEntry] = field(default_factory=list)


@dataclass
class DailyAttendancePolicy:
    skip_badge_in: bool = False
    skip_badge_out: bool = False
    badge_in_minutes: int = -1
    badge_out_minutes: int = -1
    note: str = ""


@dataclass
class NtfySettings:
    enabled: bool = False
    base_url: str = "https://ntfy.sh"
    topic: str = ""
    access_token: str = ""


@dataclass
class SchedulerSettings:
    auto_startup_enabled: bool = True
    auto_time: str = "07:00"
    exact_badge_chance_percent: int = 50
    near_badge_offset_chance_percent: int = 50


@dataclass
class DailyScheduleSnapshot:
    user_id: int = 0
    username: str = ""
    date: str = ""
    planned_at: str = ""
    in_office: bool = False
    skip_badge_in: bool = True
    skip_badge_out: bool = True
    badge_in_executed: bool = False
    badge_out_executed: bool = False
    badge_in_at: float = 0.0
    badge_out_at: float = 0.0
    note: str = ""


@dataclass
class PlanningStatusSnapshot:
    pending: bool = False
    success: bool = False
    message: str = ""
    timestamp: str = ""
