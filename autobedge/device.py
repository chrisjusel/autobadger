from __future__ import annotations

import socket

from .models import WifiCredentials
from .storage import StorageManager


class LedManager:
    def begin(self, pin: int = 19) -> None:
        self.pin = pin

    def set_wifi_connecting(self) -> None:
        pass

    def set_wifi_connected(self) -> None:
        pass

    def set_access_point_active(self) -> None:
        pass

    def set_idle(self) -> None:
        pass


class WiFiManager:
    """Linux compatibility layer for the ESP32 WiFi manager.

    VM networking is controlled by the host OS. The methods are kept so the web UI and storage
    flow remain compatible, but they only persist/display metadata.
    """

    def __init__(self, storage: StorageManager, led_manager: LedManager) -> None:
        self.storage = storage
        self.led_manager = led_manager
        self.credentials = WifiCredentials()

    def begin(self) -> None:
        self.credentials = self.storage.load_wifi_credentials() or WifiCredentials(ssid=self._hostname(), password="")
        self.led_manager.set_wifi_connected()

    def process(self) -> None:
        pass

    def handle_watchdog(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def is_provisioning_mode(self) -> bool:
        return False

    def get_connected_ssid(self) -> str:
        return self.credentials.ssid or self._hostname()

    def get_local_ip(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"

    def get_scanned_networks(self) -> list[str]:
        return [self.get_connected_ssid()]

    def request_network_scan(self) -> None:
        pass

    def is_network_scan_running(self) -> bool:
        return False

    def reset_saved_network(self) -> None:
        self.storage.clear_wifi_credentials()
        self.credentials = WifiCredentials(ssid=self._hostname(), password="")

    def queue_network_change(self, ssid: str, password: str, delay_ms: int = 1000) -> None:
        self.save_and_connect(ssid, password)

    def save_and_connect(self, ssid: str, password: str) -> bool:
        if not ssid:
            return False
        self.credentials = WifiCredentials(ssid=ssid, password=password)
        return self.storage.save_wifi_credentials(self.credentials)

    @staticmethod
    def _hostname() -> str:
        return socket.gethostname()

