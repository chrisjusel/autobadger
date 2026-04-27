from __future__ import annotations

import hashlib
import threading
from dataclasses import replace

from .models import BadgeLogEntry, UserProfile
from .storage import StorageManager
from .time_manager import NTPManager


class UserManager:
    def __init__(self, storage: StorageManager, time_manager: NTPManager | None = None) -> None:
        self.storage = storage
        self.time_manager = time_manager
        self._lock = threading.RLock()
        self._users: list[UserProfile] = []

    def begin(self) -> bool:
        users = self.storage.load_users()
        if not users:
            return self._bootstrap_default_admin()
        with self._lock:
            self._users = users
        return True

    def authenticate(self, username: str, password: str) -> UserProfile | None:
        hashed = self.hash_password(password)
        with self._lock:
            for user in self._users:
                if user.username == username and user.password_hash == hashed:
                    return replace(user, badge_log=list(user.badge_log), office_days=list(user.office_days), scheduled_pauses=list(user.scheduled_pauses))
        return None

    def get_user_by_id(self, user_id: int) -> UserProfile | None:
        with self._lock:
            for user in self._users:
                if user.id == user_id:
                    return replace(user, badge_log=list(user.badge_log), office_days=list(user.office_days), scheduled_pauses=list(user.scheduled_pauses))
        return None

    def get_all_users(self) -> list[UserProfile]:
        with self._lock:
            return [
                replace(user, badge_log=list(user.badge_log), office_days=list(user.office_days), scheduled_pauses=list(user.scheduled_pauses))
                for user in self._users
            ]

    def get_corem_enabled_users(self) -> list[UserProfile]:
        result: list[UserProfile] = []
        with self._lock:
            for user in self._users:
                has_credentials = bool(user.corem_username and user.corem_password)
                has_session = bool(user.corem_username and (user.jwt_token or user.refresh_token))
                if not user.is_admin and (has_credentials or has_session):
                    result.append(replace(user, badge_log=list(user.badge_log), office_days=list(user.office_days), scheduled_pauses=list(user.scheduled_pauses)))
        return result

    def update_user_settings(
        self,
        user_id: int,
        home_lat: float,
        home_lon: float,
        home_accuracy: int,
        office_lat: float,
        office_lon: float,
        office_accuracy: int,
        office_days: list[int],
        ntfy_enabled: bool,
        ntfy_topic: str,
    ) -> bool:
        with self._lock:
            user = self._find_user_locked(user_id)
            if user is None:
                return False
            user.home_lat = home_lat
            user.home_lon = home_lon
            user.home_accuracy = home_accuracy
            user.office_lat = office_lat
            user.office_lon = office_lon
            user.office_accuracy = office_accuracy
            user.office_days = office_days
            user.ntfy_enabled = ntfy_enabled
            user.ntfy_topic = ntfy_topic
            return self._save_locked()

    def add_scheduled_pause(self, user_id: int, date: str) -> bool:
        with self._lock:
            user = self._find_user_locked(user_id)
            if user is None:
                return False
            if date not in user.scheduled_pauses:
                user.scheduled_pauses.append(date)
                user.scheduled_pauses.sort()
            return self._save_locked()

    def remove_scheduled_pause(self, user_id: int, date: str) -> bool:
        with self._lock:
            user = self._find_user_locked(user_id)
            if user is None:
                return False
            user.scheduled_pauses = [pause for pause in user.scheduled_pauses if pause != date]
            return self._save_locked()

    def upsert_user(self, user_data: UserProfile, plain_password: str, update_password: bool) -> tuple[bool, str]:
        if not user_data.username:
            return False, "Username obbligatorio."
        with self._lock:
            duplicate = self._find_user_by_username_locked(user_data.username)
            if duplicate is not None and duplicate.id != user_data.id:
                return False, "Username gia' esistente."
            existing = self._find_user_locked(user_data.id)
            target = replace(user_data)
            if existing is not None:
                target.password_hash = existing.password_hash
                target.badge_log = existing.badge_log
                target.scheduled_pauses = existing.scheduled_pauses
                target.office_days = existing.office_days
                target.home_lat = existing.home_lat
                target.home_lon = existing.home_lon
                target.home_accuracy = existing.home_accuracy
                target.office_lat = existing.office_lat
                target.office_lon = existing.office_lon
                target.office_accuracy = existing.office_accuracy
            else:
                target.id = self._next_user_id_locked()
            if target.is_admin:
                target.corem_username = ""
                target.corem_password = ""
                target.corem_user_id = 0
                target.jwt_token = ""
                target.refresh_token = ""
                target.ntfy_enabled = False
                target.ntfy_topic = ""
            if update_password:
                if not plain_password:
                    return False, "Password obbligatoria."
                target.password_hash = self.hash_password(plain_password)
            if existing is None:
                self._users.append(target)
            else:
                self._users[self._users.index(existing)] = target
            if not self._save_locked():
                return False, "Impossibile salvare users.json."
            return True, ""

    def delete_user(self, user_id: int) -> tuple[bool, str]:
        with self._lock:
            user = self._find_user_locked(user_id)
            if user is None:
                return False, "Utente non trovato."
            if user.is_admin:
                return False, "L'utente admin non puo' essere eliminato."
            self._users = [candidate for candidate in self._users if candidate.id != user_id]
            if not self._save_locked():
                return False, "Impossibile salvare users.json."
            return True, ""

    def update_corem_session(self, user_id: int, corem_user_id: int, jwt_token: str, refresh_token: str) -> bool:
        with self._lock:
            user = self._find_user_locked(user_id)
            if user is None:
                return False
            if corem_user_id > 0:
                user.corem_user_id = corem_user_id
            user.jwt_token = jwt_token
            user.refresh_token = refresh_token
            return self._save_locked()

    def clear_corem_tokens(self, user_id: int) -> bool:
        return self.update_corem_session(user_id, 0, "", "")

    def append_badge_log(self, user_id: int, type_: str, success: bool, note: str, timestamp: str = "") -> None:
        with self._lock:
            user = self._find_user_locked(user_id)
            if user is None:
                return
            user.badge_log.append(BadgeLogEntry(timestamp=timestamp or self._make_timestamp(), type=type_, success=success, note=note))
            user.badge_log = user.badge_log[-100:]
            self._save_locked()

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def _bootstrap_default_admin(self) -> bool:
        with self._lock:
            self._users = [UserProfile(id=1, username="admin", password_hash=self.hash_password("admin123"), is_admin=True)]
            return self._save_locked()

    def _save_locked(self) -> bool:
        return self.storage.save_users(self._users)

    def _next_user_id_locked(self) -> int:
        return max((user.id for user in self._users), default=0) + 1

    def _find_user_locked(self, user_id: int) -> UserProfile | None:
        return next((user for user in self._users if user.id == user_id), None)

    def _find_user_by_username_locked(self, username: str) -> UserProfile | None:
        return next((user for user in self._users if user.username == username), None)

    def _make_timestamp(self) -> str:
        if self.time_manager is not None:
            return self.time_manager.get_current_timestamp()
        return ""

