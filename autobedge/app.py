from __future__ import annotations

import argparse
import logging
import os

from .corem_api import CoremApiManager
from .device import LedManager, WiFiManager
from .notification_manager import NotificationManager
from .scheduler import SchedulerManager
from .storage import StorageManager
from .time_manager import NTPManager
from .user_manager import UserManager
from .web import WebServerManager


def build_app(data_dir: str = "data", dry_run: bool = False, timezone: str = "Europe/Rome"):
    storage = StorageManager(data_dir)
    storage.begin()
    ntp_manager = NTPManager(timezone)
    ntp_manager.begin()
    user_manager = UserManager(storage, ntp_manager)
    user_manager.begin()
    led_manager = LedManager()
    led_manager.begin()
    wifi_manager = WiFiManager(storage, led_manager)
    wifi_manager.begin()
    notification_manager = NotificationManager(storage)
    notification_manager.begin()
    corem_api = CoremApiManager(user_manager)
    scheduler_manager = SchedulerManager(user_manager, storage, ntp_manager, corem_api, notification_manager, dry_run)
    scheduler_manager.begin()
    web = WebServerManager(user_manager, ntp_manager, scheduler_manager, notification_manager, dry_run)
    app = web.create_app()
    app.config["AUTOBEDGE_SCHEDULER"] = scheduler_manager
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AutoBedge on Linux")
    parser.add_argument("--host", default=os.environ.get("AUTOBEDGE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AUTOBEDGE_PORT", "80")))
    parser.add_argument("--data-dir", default=os.environ.get("AUTOBEDGE_DATA_DIR", "data"))
    parser.add_argument("--timezone", default=os.environ.get("AUTOBEDGE_TIMEZONE", "Europe/Rome"))
    parser.add_argument("--dry-run", action="store_true", default=os.environ.get("AUTOBEDGE_DRY_RUN", "0") == "1")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = build_app(args.data_dir, args.dry_run, args.timezone)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
