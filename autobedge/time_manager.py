from __future__ import annotations

import socket
import struct
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


class NTPManager:
    NTP_DELTA = 2_208_988_800
    RETRY_SECONDS = 900.0

    def __init__(self, timezone: str = "Europe/Rome", server: str = "pool.ntp.org", timeout: float = 3.0) -> None:
        self.tz = ZoneInfo(timezone)
        self.server = server.strip() or "pool.ntp.org"
        self.timeout = timeout
        self.synced = False
        self.last_sync_epoch = 0.0
        self.last_attempt_epoch = 0.0
        self.offset_seconds = 0.0
        self.last_error = ""

    def begin(self) -> None:
        self.sync_time()

    def sync_time(self) -> bool:
        self.last_attempt_epoch = time.time()
        try:
            offset = self._query_ntp_offset()
        except OSError as exc:
            self.synced = False
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        self.offset_seconds = offset
        self.synced = True
        self.last_sync_epoch = time.time()
        self.last_error = ""
        return True

    def maintain(self) -> None:
        if not self.synced and time.time() - self.last_attempt_epoch >= self.RETRY_SECONDS:
            self.sync_time()

    def local_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.now(), self.tz)

    def now(self) -> float:
        return time.time() + self.offset_seconds

    def get_current_date(self) -> str:
        return self.local_datetime().strftime("%Y-%m-%d")

    def get_current_timestamp(self) -> str:
        return datetime.fromtimestamp(self.now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")

    def is_synced(self) -> bool:
        return self.synced

    def get_last_sync_timestamp(self) -> str:
        if self.last_sync_epoch <= 0:
            return ""
        return datetime.fromtimestamp(self.last_sync_epoch, self.tz).strftime("%Y-%m-%dT%H:%M:%S%z")

    def get_last_error(self) -> str:
        return self.last_error

    def _query_ntp_offset(self) -> float:
        packet = b"\x1b" + 47 * b"\0"
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout)
            request_time = time.time()
            sock.sendto(packet, (self.server, 123))
            data, _ = sock.recvfrom(48)
            response_time = time.time()
        if len(data) < 48:
            raise OSError("Risposta NTP incompleta")
        seconds_2, fraction_2, seconds_3, fraction_3 = struct.unpack("!IIII", data[32:48])
        server_receive = self._ntp_to_unix(seconds_2, fraction_2)
        server_transmit = self._ntp_to_unix(seconds_3, fraction_3)
        return ((server_receive - request_time) + (server_transmit - response_time)) / 2

    @classmethod
    def _ntp_to_unix(cls, seconds: int, fraction: int) -> float:
        return seconds - cls.NTP_DELTA + fraction / 2**32
