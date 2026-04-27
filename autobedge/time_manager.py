from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo


class NTPManager:
    """Linux time provider.

    On a VM the OS clock should be synchronized by systemd-timesyncd/chrony/ntpd, so this class
    mirrors the firmware API without trying to configure NTP from the application.
    """

    def __init__(self, timezone: str = "Europe/Rome") -> None:
        self.tz = ZoneInfo(timezone)
        self.synced = False
        self.last_sync_epoch = 0.0

    def begin(self) -> None:
        self.sync_time()

    def sync_time(self) -> bool:
        self.synced = True
        self.last_sync_epoch = time.time()
        return True

    def maintain(self) -> None:
        if not self.synced:
            self.sync_time()

    def local_datetime(self) -> datetime:
        return datetime.now(self.tz)

    def now(self) -> float:
        return time.time()

    def get_current_date(self) -> str:
        return self.local_datetime().strftime("%Y-%m-%d")

    def get_current_timestamp(self) -> str:
        return self.local_datetime().strftime("%Y-%m-%dT%H:%M:%S%z")

    def is_synced(self) -> bool:
        return self.synced

    def get_last_sync_timestamp(self) -> str:
        if self.last_sync_epoch <= 0:
            return ""
        return datetime.fromtimestamp(self.last_sync_epoch, self.tz).strftime("%Y-%m-%dT%H:%M:%S%z")

