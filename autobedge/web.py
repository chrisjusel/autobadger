from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

from flask import Flask, Response, redirect, render_template, request, session, url_for

from .models import DailyScheduleSnapshot, NtfySettings, SchedulerSettings, UserProfile
from .notification_manager import NotificationManager
from .scheduler import SchedulerManager
from .time_manager import NTPManager
from .user_manager import UserManager


class WebServerManager:
    def __init__(
        self,
        user_manager: UserManager,
        ntp_manager: NTPManager,
        scheduler_manager: SchedulerManager,
        notification_manager: NotificationManager,
        dry_run: bool,
    ) -> None:
        self.user_manager = user_manager
        self.ntp_manager = ntp_manager
        self.scheduler_manager = scheduler_manager
        self.notification_manager = notification_manager
        self.dry_run = dry_run

    def create_app(self) -> Flask:
        app = Flask(__name__)
        app.secret_key = os.environ.get("AUTOBEDGE_SECRET_KEY", secrets.token_hex(32))
        self._configure_routes(app)
        return app

    def _configure_routes(self, app: Flask) -> None:
        @app.get("/favicon.ico")
        def favicon_ico() -> Response:
            return redirect(url_for("static", filename="favicon.svg"))

        @app.get("/")
        def root() -> Response | str:
            if self._current_user():
                return redirect(url_for("dashboard"))
            return redirect(url_for("login"))

        @app.get("/login")
        def login() -> str | Response:
            if self._current_user():
                return redirect(url_for("dashboard"))
            return self._login_page(request.args.get("msg", ""))

        @app.post("/login")
        def login_post() -> str | Response:
            user = self.user_manager.authenticate(request.form.get("username", ""), request.form.get("password", ""))
            if user is None:
                return self._login_page("Credenziali non valide.")
            session.clear()
            session["user_id"] = user.id
            return redirect(url_for("dashboard"))

        @app.get("/logout")
        def logout() -> Response:
            session.clear()
            return redirect(self._with_msg("login", "Logout eseguito"))

        @app.get("/dashboard")
        def dashboard() -> str | Response:
            user = self._require_auth()
            if not isinstance(user, UserProfile):
                return user
            planning_status = self.scheduler_manager.get_planning_status()
            if planning_status.pending:
                return self._planning_pending_page(user, planning_status.message)
            return self._dashboard_page(user, request.args.get("msg", ""))

        @app.post("/dashboard/scheduler/replan")
        def dashboard_replan() -> Response:
            user = self._require_auth()
            if not isinstance(user, UserProfile):
                return user
            date = self.ntp_manager.get_current_date()
            ok, message = self.scheduler_manager.trigger_planning_for_date(date, 0 if user.is_admin else user.id)
            return redirect(url_for("dashboard") if ok and message == "Pianificazione messa in coda." else self._with_msg("dashboard", message))

        @app.post("/dashboard/scheduler/delete")
        def dashboard_scheduler_delete() -> Response:
            user = self._require_auth()
            if not isinstance(user, UserProfile):
                return user
            user_id = self._to_int(request.form.get("user_id"), 0) if user.is_admin else user.id
            _, message = self.scheduler_manager.cancel_planning_for_date(request.form.get("date", ""), user_id)
            return redirect(self._with_msg("dashboard", message))

        @app.get("/settings")
        def settings() -> str | Response:
            user = self._require_non_admin()
            if not isinstance(user, UserProfile):
                return user
            return self._settings_page(user, request.args.get("msg", ""))

        @app.post("/settings")
        def settings_post() -> Response:
            user = self._require_non_admin()
            if not isinstance(user, UserProfile):
                return user
            office_days = [int(value) for value in request.form.getlist("office_day") if value.isdigit()]
            ok = self.user_manager.update_user_settings(
                user.id,
                self._to_float(request.form.get("home_lat")),
                self._to_float(request.form.get("home_lon")),
                self._to_int(request.form.get("home_accuracy"), 50),
                self._to_float(request.form.get("office_lat")),
                self._to_float(request.form.get("office_lon")),
                self._to_int(request.form.get("office_accuracy"), 50),
                office_days,
                request.form.get("ntfy_enabled") == "on",
                request.form.get("ntfy_topic", ""),
            )
            if not ok:
                return redirect(self._with_msg("settings", "Errore salvataggio"))
            saved_user = self.user_manager.get_user_by_id(user.id)
            if request.form.get("submit_action") == "test_ntfy" and saved_user:
                test_ok, error = self.notification_manager.send_user_test_notification(saved_user, saved_user.username)
                return redirect(self._with_msg("settings", "Notifica ntfy utente inviata" if test_ok else error))
            return redirect(self._with_msg("settings", "Impostazioni salvate"))

        @app.get("/pauses")
        def pauses() -> str | Response:
            user = self._require_non_admin()
            if not isinstance(user, UserProfile):
                return user
            return self._pauses_page(user, request.args.get("msg", ""))

        @app.post("/pauses/add")
        def pauses_add() -> Response:
            user = self._require_non_admin()
            if not isinstance(user, UserProfile):
                return user
            date = request.form.get("date", "")
            if not date:
                return redirect(self._with_msg("pauses", "Data obbligatoria"))
            ok = self.user_manager.add_scheduled_pause(user.id, date)
            return redirect(self._with_msg("pauses", "Pausa aggiunta" if ok else "Errore salvataggio"))

        @app.get("/pauses/delete")
        def pauses_delete() -> Response:
            user = self._require_non_admin()
            if not isinstance(user, UserProfile):
                return user
            ok = self.user_manager.remove_scheduled_pause(user.id, request.args.get("date", ""))
            return redirect(self._with_msg("pauses", "Pausa rimossa" if ok else "Errore rimozione"))

        @app.post("/pauses/cancel-today")
        def pauses_cancel_today() -> Response:
            user = self._require_non_admin()
            if not isinstance(user, UserProfile):
                return user
            _, message = self.scheduler_manager.skip_remaining_today_for_user(user.id)
            return redirect(self._with_msg("dashboard", message))

        @app.get("/diagnostics")
        def diagnostics() -> str | Response:
            user = self._require_admin()
            if not isinstance(user, UserProfile):
                return user
            return self._diagnostics_page(user, request.args.get("msg", ""))

        @app.post("/admin/scheduler/replan")
        def admin_scheduler_replan() -> Response:
            user = self._require_admin()
            if not isinstance(user, UserProfile):
                return user
            ok, message = self.scheduler_manager.trigger_planning_for_date(request.form.get("date", ""), self._to_int(request.form.get("user_id"), 0))
            return redirect(url_for("diagnostics") if ok and message == "Pianificazione messa in coda." else self._with_msg("diagnostics", message))

        @app.post("/admin/scheduler/delete")
        def admin_scheduler_delete() -> Response:
            user = self._require_admin()
            if not isinstance(user, UserProfile):
                return user
            _, message = self.scheduler_manager.cancel_planning_for_date(request.form.get("date", ""), self._to_int(request.form.get("user_id"), 0))
            return redirect(self._with_msg("diagnostics", message))

        @app.get("/admin")
        def admin() -> str | Response:
            user = self._require_admin()
            if not isinstance(user, UserProfile):
                return user
            return self._admin_page(user, request.args.get("msg", ""))

        @app.get("/admin/user")
        def admin_user() -> str | Response:
            current = self._require_admin()
            if not isinstance(current, UserProfile):
                return current
            editing = self.user_manager.get_user_by_id(self._to_int(request.args.get("id"), 0)) if request.args.get("id") else None
            return self._admin_user_page(current, editing, request.args.get("msg", ""))

        @app.post("/admin/user")
        def admin_user_post() -> Response:
            current = self._require_admin()
            if not isinstance(current, UserProfile):
                return current
            submitted = UserProfile(
                id=self._to_int(request.form.get("id"), 0),
                username=request.form.get("username", ""),
                corem_username=request.form.get("corem_username", ""),
                corem_password=request.form.get("corem_password", ""),
                corem_user_id=max(0, self._to_int(request.form.get("corem_user_id"), 0)),
                ntfy_enabled=request.form.get("ntfy_enabled") == "on",
                ntfy_topic=request.form.get("ntfy_topic", ""),
                is_admin=request.form.get("is_admin") == "on",
            )
            if submitted.id == 1:
                submitted.is_admin = True
            plain_password = request.form.get("password", "")
            update_password = submitted.id == 0 or bool(plain_password)
            ok, error = self.user_manager.upsert_user(submitted, plain_password, update_password)
            if not ok:
                return redirect(self._with_msg("admin_user", error, id=submitted.id))
            if request.form.get("submit_action") == "test_ntfy":
                saved = self._find_user_by_username(submitted.username)
                if not saved:
                    return redirect(self._with_msg("admin_user", "Utente non trovato dopo il salvataggio", id=submitted.id))
                test_ok, test_error = self.notification_manager.send_user_test_notification(saved, current.username)
                return redirect(self._with_msg("admin_user", "Notifica ntfy utente inviata" if test_ok else test_error, id=saved.id))
            return redirect(self._with_msg("admin", "Utente salvato"))

        @app.get("/admin/delete")
        def admin_delete() -> Response:
            user = self._require_admin()
            if not isinstance(user, UserProfile):
                return user
            ok, error = self.user_manager.delete_user(self._to_int(request.args.get("id"), 0))
            return redirect(self._with_msg("admin", "Utente eliminato" if ok else error))

        @app.post("/admin/ntfy")
        def admin_ntfy() -> Response:
            user = self._require_admin()
            if not isinstance(user, UserProfile):
                return user
            settings = NtfySettings(enabled=request.form.get("enabled") == "on", base_url=request.form.get("base_url", ""), topic=request.form.get("topic", ""), access_token=request.form.get("access_token", ""))
            ok, error = self.notification_manager.update_settings(settings)
            if ok and request.form.get("submit_action") == "test_ntfy":
                test_ok, test_error = self.notification_manager.send_test_notification(user.username)
                return redirect(self._with_msg("admin", "Notifica ntfy globale inviata" if test_ok else test_error))
            return redirect(self._with_msg("admin", "Configurazione ntfy salvata" if ok else error))

        @app.post("/admin/scheduler/settings")
        def admin_scheduler_settings() -> Response:
            user = self._require_admin()
            if not isinstance(user, UserProfile):
                return user
            settings = SchedulerSettings(
                auto_startup_enabled=request.form.get("auto_startup_enabled") == "on",
                auto_time=request.form.get("auto_time", "07:00"),
                exact_badge_chance_percent=self._to_int(request.form.get("exact_badge_chance_percent"), 50),
                near_badge_offset_chance_percent=self._to_int(request.form.get("near_badge_offset_chance_percent"), 50),
            )
            ok, error = self.scheduler_manager.update_settings(settings)
            return redirect(self._with_msg("admin", "Configurazione scheduler salvata" if ok else error))

    def _current_user(self) -> UserProfile | None:
        user_id = session.get("user_id")
        return self.user_manager.get_user_by_id(int(user_id)) if user_id else None

    def _require_auth(self) -> UserProfile | Response:
        user = self._current_user()
        if user is None:
            return redirect(self._with_msg("login", "Sessione non valida"))
        return user

    def _require_admin(self) -> UserProfile | Response:
        user = self._require_auth()
        if not isinstance(user, UserProfile):
            return user
        if not user.is_admin:
            return redirect(self._with_msg("dashboard", "Accesso negato"))
        return user

    def _require_non_admin(self) -> UserProfile | Response:
        user = self._require_auth()
        if not isinstance(user, UserProfile):
            return user
        if user.is_admin:
            return redirect(self._with_msg("dashboard", "Pagina non disponibile per admin"))
        return user

    def _render(self, template: str, title: str, user: UserProfile | None = None, message: str = "", **context: object) -> str:
        return render_template(
            template,
            title=title,
            user=user,
            message=message,
            dry_run=self.dry_run,
            nav_links=self._nav_links(user) if user else [],
            fmt_date=self._fmt_date,
            fmt_datetime=self._fmt_datetime,
            schedule_cell=self._schedule_cell,
            **context,
        )

    def _nav_links(self, user: UserProfile | None) -> list[dict[str, str | bool]]:
        if user is None:
            return []
        current_path = request.path
        links = [self._nav_link("/dashboard", "Dashboard", current_path)]
        if not user.is_admin:
            links.extend([self._nav_link("/settings", "Impostazioni", current_path), self._nav_link("/pauses", "Pause", current_path)])
        if user.is_admin:
            links.extend([self._nav_link("/admin", "Admin", current_path), self._nav_link("/diagnostics", "Diagnostica", current_path)])
        links.append(self._nav_link("/logout", "Logout", current_path))
        return links

    @staticmethod
    def _nav_link(href: str, label: str, current_path: str) -> dict[str, str | bool]:
        active = current_path == href or (href != "/dashboard" and current_path.startswith(f"{href}/"))
        return {"href": href, "label": label, "active": active}

    def _login_page(self, message: str) -> str:
        return self._render("login.html", "Login", message=message)

    def _planning_pending_page(self, user: UserProfile, message: str) -> str:
        return self._render("planning_pending.html", "Pianificazione in corso", user, pending_message=message)

    def _dashboard_page(self, user: UserProfile, message: str) -> str:
        users = self.user_manager.get_all_users() if user.is_admin else [user]
        schedules = [entry for entry in self.scheduler_manager.get_schedules_snapshot() if user.is_admin or entry.user_id == user.id]
        logs = []
        for candidate in users:
            for entry in candidate.badge_log:
                logs.append({"username": candidate.username, "entry": entry})
        logs.sort(key=lambda row: row["entry"].timestamp, reverse=True)
        last_planned_at = max((entry.planned_at for entry in schedules if entry.planned_at), default="")
        return self._render("dashboard.html", "Dashboard", user, message, schedules=schedules, logs=logs[:30], last_planned_at=last_planned_at)

    def _settings_page(self, user: UserProfile, message: str) -> str:
        return self._render("settings.html", "Impostazioni", user, message, day_labels=["Lun", "Mar", "Mer", "Gio", "Ven"])

    def _pauses_page(self, user: UserProfile, message: str) -> str:
        return self._render("pauses.html", "Pause", user, message)

    def _diagnostics_page(self, user: UserProfile, message: str) -> str:
        return self._render(
            "diagnostics.html",
            "Diagnostica",
            user,
            message,
            corem_users=self.user_manager.get_corem_enabled_users(),
            current_date=self.ntp_manager.get_current_date(),
        )

    def _admin_page(self, user: UserProfile, message: str) -> str:
        return self._render(
            "admin.html",
            "Admin",
            user,
            message,
            ntfy=self.notification_manager.get_settings(),
            scheduler=self.scheduler_manager.get_settings(),
            users=self.user_manager.get_all_users(),
        )

    def _admin_user_page(self, current: UserProfile, editing: UserProfile | None, message: str) -> str:
        return self._render("admin_user.html", "Utente", current, message, target=editing or UserProfile(), is_edit=editing is not None)

    def _find_user_by_username(self, username: str) -> UserProfile | None:
        return next((user for user in self.user_manager.get_all_users() if user.username == username), None)

    def _with_msg(self, endpoint: str, message: str, **values: object) -> str:
        params = dict(values)
        params["msg"] = message
        return f"{url_for(endpoint)}?{urlencode(params)}"

    @staticmethod
    def _to_int(value: str | None, default: int = 0) -> int:
        try:
            return int(value or default)
        except ValueError:
            return default

    @staticmethod
    def _to_float(value: str | None, default: float = 0.0) -> float:
        try:
            return float(value or default)
        except ValueError:
            return default

    @staticmethod
    def _fmt_date(value: str) -> str:
        return f"{value[8:10]}/{value[5:7]}/{value[0:4]}" if len(value) >= 10 and value[4] == "-" and value[7] == "-" else value

    def _fmt_datetime(self, value: str) -> str:
        if not value:
            return "-"
        text = str(value).strip()
        if len(text) >= 19 and text[4] == "-" and text[7] == "-" and text[10] in ("T", " "):
            try:
                parsed = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S" if text[10] == "T" else "%Y-%m-%d %H:%M:%S")
                return parsed.replace(tzinfo=timezone.utc).astimezone(self.ntp_manager.tz).strftime("%d/%m/%Y %H:%M")
            except ValueError:
                pass
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return self._fmt_date(text)
        return text

    def _schedule_cell(self, epoch: float, skipped: bool, executed: bool) -> str:
        if skipped:
            return "Skip"
        value = self._fmt_epoch(epoch)
        return f"{value} (eseguito)" if executed else value

    def _fmt_epoch(self, epoch: float) -> str:
        if epoch <= 0:
            return "-"
        return datetime.fromtimestamp(epoch, self.ntp_manager.tz).strftime("%d/%m/%Y %H:%M")
