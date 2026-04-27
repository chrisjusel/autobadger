from __future__ import annotations

import calendar
import logging
import time
from datetime import datetime
from typing import Any

import requests

from .models import DailyAttendancePolicy, UserProfile
from .user_manager import UserManager

LOG = logging.getLogger(__name__)


class CoremApiManager:
    BASE_URL = "https://gestionedipendenti.corem.cloud/api"
    RETRY_DELAYS = (5, 15, 45)

    def __init__(self, user_manager: UserManager, timeout: float = 20.0) -> None:
        self.user_manager = user_manager
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) CoremBadger/1.0",
            }
        )

    def login_user(self, user: UserProfile) -> tuple[bool, str]:
        response, error = self._execute_request("POST", f"{self.BASE_URL}/auth/login", json={"username": user.corem_username, "password": user.corem_password})
        if response is None:
            self._log_failure(user, "SYS", f"Login Corem fallito: {error}")
            return False, error
        if not 200 <= response.status_code < 300:
            message = f"HTTP {response.status_code} durante login"
            self._log_failure(user, "SYS", message)
            return False, message
        try:
            data = response.json()
        except ValueError:
            message = "Risposta login Corem non valida"
            self._log_failure(user, "SYS", message)
            return False, message
        user.jwt_token = str(data.get("token") or "")
        user.refresh_token = str(data.get("refreshToken") or "")
        self.user_manager.update_corem_session(user.id, user.corem_user_id, user.jwt_token, user.refresh_token)
        return bool(user.jwt_token), "" if user.jwt_token else "Token Corem assente"

    def fetch_holidays(self, user: UserProfile) -> tuple[bool, list[str], str]:
        response, error = self._execute_authorized_request(user, "GET", "/sedi/100/festivita", None, "SYS", "recupero festivita'")
        if response is None:
            return False, [], error
        try:
            data = response.json()
        except ValueError:
            message = "JSON festivita' non valido"
            self._log_failure(user, "SYS", message)
            return False, [], message
        if not isinstance(data, list):
            message = "JSON festivita' non valido"
            self._log_failure(user, "SYS", message)
            return False, [], message
        holidays = sorted({str(item.get("date")) for item in data if isinstance(item, dict) and item.get("date")})
        return True, holidays, ""

    def fetch_daily_policy(self, user: UserProfile, date: str) -> tuple[bool, DailyAttendancePolicy, str]:
        policy = DailyAttendancePolicy()
        if user.corem_user_id <= 0:
            message = "utenteId Corem non configurato"
            self._log_failure(user, "SYS", message)
            return False, policy, message
        year = int(date[:4])
        month = int(date[5:7])
        month_start = f"{date[:8]}01"
        month_end = f"{date[:8]}{calendar.monthrange(year, month)[1]:02d}"
        path = f"/eventi?data_inizio={month_start}&data_fine={month_end}&utente_id={user.corem_user_id}"
        response, error = self._execute_authorized_request(user, "GET", path, None, "SYS", "recupero eventi giornalieri")
        if response is None:
            return False, policy, error
        try:
            data = response.json()
        except ValueError:
            message = "JSON eventi non valido"
            self._log_failure(user, "SYS", message)
            return False, policy, message
        if not isinstance(data, list):
            message = "JSON eventi non valido"
            self._log_failure(user, "SYS", message)
            return False, policy, message
        for item in data:
            if isinstance(item, dict):
                self._apply_event_to_policy(policy, item, date)
        return True, policy, ""

    def submit_badge(self, user: UserProfile, in_office: bool, type_: str) -> tuple[bool, str]:
        payload = {
            "inSede": True,
            "sedeId": 100,
            "geoPosInfo": {
                "latitudine": user.office_lat if in_office else user.home_lat,
                "longitudine": user.office_lon if in_office else user.home_lon,
                "accuratezza": user.office_accuracy if in_office else user.home_accuracy,
            },
        }
        response, error = self._execute_authorized_request(user, "POST", "/presenze/telelavoro", payload, type_, f"registrazione badge {type_}")
        if response is None:
            return False, error
        return True, "Registrato in sede"

    def _execute_authorized_request(
        self,
        user: UserProfile,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        log_type: str,
        context: str,
    ) -> tuple[requests.Response | None, str]:
        if not user.jwt_token:
            ok, error = self.login_user(user)
            if not ok:
                return None, error
        response, error = self._execute_request(method, self.BASE_URL + path, json=payload, token=user.jwt_token)
        if response is None:
            self._log_failure(user, log_type, f"{context}: {error}")
            return None, error
        if response.status_code in (401, 403):
            self.user_manager.clear_corem_tokens(user.id)
            user.jwt_token = ""
            user.refresh_token = ""
            ok, login_error = self.login_user(user)
            if not ok:
                message = f"{context}: refresh JWT fallito"
                self._log_failure(user, log_type, message)
                return None, login_error or message
            response, error = self._execute_request(method, self.BASE_URL + path, json=payload, token=user.jwt_token)
            if response is None:
                self._log_failure(user, log_type, f"{context}: {error}")
                return None, error
        if 200 <= response.status_code < 300:
            return response, ""
        message = f"HTTP {response.status_code}"
        self._log_failure(user, log_type, f"{context}: {message}")
        return None, message

    def _execute_request(self, method: str, url: str, json: dict[str, Any] | None = None, token: str = "") -> tuple[requests.Response | None, str]:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        attempts = len(self.RETRY_DELAYS) + 1
        last_error = ""
        for attempt in range(attempts):
            if attempt:
                time.sleep(self.RETRY_DELAYS[attempt - 1])
            try:
                response = self.session.request(method, url, json=json, headers=headers, timeout=self.timeout)
                LOG.info("[Corem] %s %s -> HTTP %s", method, url.replace(self.BASE_URL, ""), response.status_code)
                if response.status_code < 500 or response.status_code in (401, 403):
                    return response, ""
                last_error = f"HTTP {response.status_code}"
            except requests.RequestException as exc:
                last_error = f"Errore rete {exc}"
                LOG.warning("[Corem] %s %s failed: %s", method, url, exc)
        return None, last_error

    def _log_failure(self, user: UserProfile, type_: str, note: str) -> None:
        LOG.warning("[Corem] %s: %s", user.username, note)
        self.user_manager.append_badge_log(user.id, type_, False, note)

    @classmethod
    def _apply_event_to_policy(cls, policy: DailyAttendancePolicy, item: dict[str, Any], date: str) -> None:
        tipo_evento = str(item.get("tipoEvento") or "").strip()
        assenza = bool(item.get("assenza", False))
        nome = cls._localized_event_name(item)
        data_inizio = str(item.get("dataInizio") or "").strip()
        data_fine = str(item.get("dataFine") or "").strip()
        if not cls._event_intersects_date(data_inizio, data_fine, date) or not tipo_evento:
            return
        if tipo_evento == "GIORNALIERO" and assenza and ("ferie" in nome.lower() or "festiv" in nome.lower()):
            policy.skip_badge_in = True
            policy.skip_badge_out = True
            policy.note = f"Assenza giornaliera: {nome}"
            return
        if tipo_evento != "ORARIO" or not assenza:
            return
        start_minutes = cls._time_from_datetime(str(item.get("oraInizio") or item.get("orarioInizio") or item.get("dataInizio") or ""))
        end_minutes = cls._time_from_datetime(str(item.get("oraFine") or item.get("orarioFine") or item.get("dataFine") or ""))
        if cls._includes_minute(start_minutes, end_minutes, 9 * 60) or cls._is_within_five_minutes(start_minutes, 9 * 60):
            if 9 * 60 < end_minutes < 18 * 60:
                policy.badge_in_minutes = end_minutes
                cls._append_policy_note(policy, "Permesso orario in ingresso: badge IN posticipato")
            else:
                policy.skip_badge_in = True
                cls._append_policy_note(policy, "Permesso orario in ingresso")
        if cls._includes_minute(start_minutes, end_minutes, 18 * 60) or cls._is_within_five_minutes(end_minutes, 18 * 60):
            if 9 * 60 < start_minutes < 18 * 60:
                policy.badge_out_minutes = start_minutes
                cls._append_policy_note(policy, "Permesso orario in uscita: badge OUT anticipato")
            else:
                policy.skip_badge_out = True
                cls._append_policy_note(policy, "Permesso orario in uscita")

    @staticmethod
    def _localized_event_name(item: dict[str, Any]) -> str:
        name = str(item.get("nome") or "").strip()
        if name:
            return name
        fallback = ""
        for localization in item.get("localizzazioni", []):
            if not isinstance(localization, dict):
                continue
            loc_name = str(localization.get("nome") or "").strip()
            if not loc_name:
                continue
            if str(localization.get("lingua") or "") == "it":
                return loc_name
            fallback = fallback or loc_name
        return fallback

    @staticmethod
    def _time_from_datetime(value: str) -> int:
        if "T" in value:
            value = value.split("T", 1)[1]
        value = value[:5]
        try:
            parsed = datetime.strptime(value, "%H:%M")
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            return -1

    @staticmethod
    def _date_from_datetime(value: str) -> str:
        return value[:10] if len(value) >= 10 and value[4] == "-" and value[7] == "-" else ""

    @classmethod
    def _event_intersects_date(cls, start: str, end: str, date: str) -> bool:
        start_date = cls._date_from_datetime(start)
        end_date = cls._date_from_datetime(end)
        if not start_date and not end_date:
            return True
        if start_date and start_date <= date and (not end_date or end_date >= date):
            return True
        return not start_date and bool(end_date) and end_date >= date

    @staticmethod
    def _includes_minute(start: int, end: int, target: int) -> bool:
        return start >= 0 and end >= 0 and start <= target <= end

    @staticmethod
    def _is_within_five_minutes(actual: int, target: int) -> bool:
        return actual >= 0 and abs(actual - target) <= 5

    @staticmethod
    def _append_policy_note(policy: DailyAttendancePolicy, note: str) -> None:
        policy.note = note if not policy.note else f"{policy.note} | {note}"

