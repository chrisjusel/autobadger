from __future__ import annotations

import os
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

from .models import NtfySettings, UserProfile
from .storage import StorageManager


class NotificationManager:
    def __init__(self, storage: StorageManager, timeout: float = 10.0) -> None:
        self.storage = storage
        self.timeout = timeout
        self.settings = NtfySettings()

    def begin(self) -> None:
        loaded = self.storage.load_ntfy_settings()
        if loaded is not None:
            loaded.base_url = self.normalize_base_url(loaded.base_url)
            loaded.topic = self.normalize_topic(loaded.topic)
            loaded.access_token = loaded.access_token.strip()
            self.settings = loaded

    def get_settings(self) -> NtfySettings:
        return NtfySettings(**self.settings.__dict__)

    def update_settings(self, settings: NtfySettings) -> tuple[bool, str]:
        normalized = NtfySettings(
            enabled=settings.enabled,
            base_url=self.normalize_base_url(settings.base_url) or "https://ntfy.sh",
            topic=self.normalize_topic(settings.topic),
            access_token=settings.access_token.strip(),
        )
        if not normalized.base_url.startswith(("http://", "https://")):
            return False, "URL server ntfy non valido. Usa http:// o https://."
        if not self.storage.save_ntfy_settings(normalized):
            return False, "Impossibile salvare configurazione ntfy."
        self.settings = normalized
        return True, ""

    def send_test_notification(self, actor: str) -> tuple[bool, str]:
        settings = self.get_settings()
        if not settings.enabled:
            return False, "Notifiche ntfy disabilitate."
        if not settings.topic:
            return False, "Topic ntfy globale non configurato."
        message = f"Test notifica ntfy inviato dal pannello admin.\nOperatore: {actor}\nEsito: configurazione raggiungibile\n"
        return self._publish(settings, "Test notifica ntfy", message, "bell,test_tube", "high")

    def send_user_test_notification(self, user: UserProfile, actor: str) -> tuple[bool, str]:
        settings = self.get_settings()
        if not settings.enabled:
            return False, "Supporto ntfy globale disabilitato."
        if not user.ntfy_enabled:
            return False, "Notifiche ntfy disabilitate per questo utente."
        settings.topic = self.normalize_topic(user.ntfy_topic)
        if not settings.topic:
            return False, "Topic ntfy utente non configurato."
        message = f"Test notifica ntfy inviato dal profilo utente.\nUtente: {user.username}\nOperatore: {actor}\nEsito: configurazione utente raggiungibile\n"
        return self._publish(settings, "Test notifica ntfy utente", message, "bell,test_tube", "high")

    def send_badge_notification(self, user: UserProfile, in_office: bool, type_: str, note: str, timestamp: str, dry_run: bool) -> bool:
        settings = self.get_settings()
        if not settings.enabled or not user.ntfy_enabled:
            return False
        settings.topic = self.normalize_topic(user.ntfy_topic)
        if not settings.topic:
            return False
        message = f"Utente: {user.username}\nBadge: {type_}\nData: {self._format_italian_datetime(timestamp) if timestamp else 'n/d'}\n"
        if note:
            message += f"Nota: {note}\n"
        if dry_run:
            message += "Esecuzione: DRY RUN\n"
        ok, _ = self._publish(settings, f"Badge {type_} eseguito", message, f"white_check_mark,{'arrow_right' if type_ == 'IN' else 'arrow_left'}", "default")
        return ok

    @staticmethod
    def normalize_base_url(value: str) -> str:
        return value.strip().rstrip("/")

    @staticmethod
    def normalize_topic(value: str) -> str:
        return value.strip().strip("/")

    def _publish(self, settings: NtfySettings, title: str, message: str, tags: str, priority: str) -> tuple[bool, str]:
        url = f"{settings.base_url}/{quote(settings.topic, safe='')}"
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "X-Title": title,
            "X-Priority": priority,
            "X-Tags": tags,
            "User-Agent": "CoremBadger/1.0",
        }
        if settings.access_token:
            headers["Authorization"] = f"Bearer {settings.access_token}"
        try:
            response = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            return False, f"Errore rete ntfy {exc}"
        if 200 <= response.status_code < 300:
            return True, ""
        detail = f"ntfy HTTP {response.status_code}"
        if response.text:
            detail += f": {response.text}"
        return False, detail

    @staticmethod
    def _format_italian_datetime(value: str) -> str:
        if len(value) >= 19 and value[4] == "-" and value[7] == "-" and value[10] in ("T", " "):
            try:
                parsed = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S" if value[10] == "T" else "%Y-%m-%d %H:%M:%S")
                tz = ZoneInfo(os.environ.get("AUTOBEDGE_TIMEZONE", "Europe/Rome"))
                return parsed.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                return f"{value[8:10]}/{value[5:7]}/{value[0:4]} {value[11:16]}"
        if len(value) >= 10 and value[4] == "-" and value[7] == "-":
            return f"{value[8:10]}/{value[5:7]}/{value[0:4]}"
        return value
