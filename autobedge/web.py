from __future__ import annotations

import html
import os
import secrets
from urllib.parse import quote

from flask import Flask, Response, redirect, request, session, url_for

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

    def _page(self, title: str, body: str, user: UserProfile | None = None) -> str:
        nav = self._navigation(user) if user else ""
        banner = "<div class='banner'>MODALITA' DRY RUN ATTIVA</div>" if self.dry_run else ""
        return f"""<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{self._e(title)}</title><style>
:root{{--bg:#07131f;--panel:#10243a;--muted:#a9bed5;--text:#f7fbff;--accent:#4ecca3;--danger:#ff6b6b;--line:rgba(255,255,255,.12)}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;color:var(--text);font-family:Trebuchet MS,Segoe UI,sans-serif;background:radial-gradient(circle at top left,rgba(78,204,163,.18),transparent 30%),linear-gradient(180deg,#081421,#07111d);line-height:1.45}}
a{{color:#77ffd1;text-decoration:none}}.wrap{{max-width:1160px;margin:0 auto;padding:16px 16px 56px}}.banner{{background:#b42323;color:white;text-align:center;font-weight:800;padding:12px}}
.card{{background:linear-gradient(180deg,rgba(19,43,69,.96),rgba(12,31,49,.95));border:1px solid var(--line);border-radius:22px;padding:20px;margin-bottom:18px;box-shadow:0 18px 55px rgba(0,0,0,.28)}}
.hero{{border-color:rgba(78,204,163,.34)}}h1,h2,h3{{margin:0 0 10px}}p{{margin:0 0 10px}}.muted{{color:var(--muted)}}.msg{{padding:14px 16px;border:1px solid rgba(78,204,163,.30);background:rgba(78,204,163,.12);border-radius:16px;margin-bottom:16px}}
.nav{{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between}}.links{{display:flex;gap:10px;flex-wrap:wrap}}.pill,.btn,button{{display:inline-flex;align-items:center;justify-content:center;border-radius:14px;border:1px solid var(--line);padding:11px 14px;font-weight:800;min-height:44px;cursor:pointer}}
.pill{{background:rgba(255,255,255,.05);color:var(--text)}}.btn,button{{background:linear-gradient(135deg,var(--accent),#39b28b);color:#072217}}.danger{{background:linear-gradient(135deg,#ff8989,#ff5f73)!important;color:#30090d!important}}.alt{{background:linear-gradient(135deg,#63a4ff,#3a78e0)!important;color:#071a38!important}}.iconbtn{{width:44px;padding:0;font-size:1.1rem;line-height:1}}
.grid,.split,.stats{{display:grid;gap:14px}}.split{{grid-template-columns:repeat(2,minmax(0,1fr))}}.grid{{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}}.stats{{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}}
input,select{{width:100%;min-height:48px;padding:12px;border-radius:14px;border:1px solid var(--line);background:rgba(4,15,24,.42);color:var(--text);margin-top:7px}}input[type=checkbox]{{width:18px;min-height:0;height:18px;padding:0;margin:0;border:0;background:transparent;accent-color:var(--accent);flex:0 0 auto}}label{{font-weight:800}}.check{{display:flex;align-items:center;gap:8px;width:max-content;max-width:100%;margin:8px 0}}.checkrow{{display:flex;gap:10px;flex-wrap:wrap}}.checkrow label{{padding:10px 12px;border:1px solid var(--line);border-radius:14px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--muted);font-size:.8rem;text-transform:uppercase}}.table{{overflow:auto}}.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}}.stat{{padding:14px;border:1px solid var(--line);border-radius:18px;background:rgba(255,255,255,.04)}}.stat b{{display:block;font-size:1.35rem}}
@media(max-width:800px){{.split{{grid-template-columns:1fr}}.links{{display:grid;grid-template-columns:1fr 1fr;width:100%}}.pill,.btn,button{{width:100%}}}}
</style></head><body>{banner}<div class="wrap">{nav}{body}</div></body></html>"""

    def _navigation(self, user: UserProfile | None) -> str:
        if user is None:
            return ""
        links = ["<a class='pill' href='/dashboard'>Dashboard</a>"]
        if not user.is_admin:
            links.extend(["<a class='pill' href='/settings'>Impostazioni</a>", "<a class='pill' href='/pauses'>Pause</a>"])
        if user.is_admin:
            links.extend(["<a class='pill' href='/admin'>Admin</a>", "<a class='pill' href='/diagnostics'>Diagnostica</a>"])
        links.append("<a class='pill' href='/logout'>Logout</a>")
        return f"<div class='card nav'><div><b>Corem Badger</b><div class='muted'>{self._e(user.username)} - {'Admin' if user.is_admin else 'Utente'}</div></div><div class='links'>{''.join(links)}</div></div>"

    def _login_page(self, message: str) -> str:
        msg = self._msg(message)
        body = f"<div class='card hero' style='max-width:560px;margin:8vh auto'><h1>Accedi al pannello</h1><p class='muted'>Sessione locale valida via cookie Flask.</p>{msg}<form method='post'><label>Username<input name='username' required></label><label>Password<input type='password' name='password' required></label><div class='actions'><button>Accedi</button></div></form></div>"
        return self._page("Login", body)

    def _planning_pending_page(self, user: UserProfile, message: str) -> str:
        return self._page("Pianificazione in corso", f"<meta http-equiv='refresh' content='1'><div class='card'><h1>Aggiornamento pianificazione in corso</h1><p>{self._e(message)}</p></div>", user)

    def _dashboard_page(self, user: UserProfile, message: str) -> str:
        users = self.user_manager.get_all_users() if user.is_admin else [user]
        schedules = self.scheduler_manager.get_schedules_snapshot()
        logs = []
        for candidate in users:
            for entry in candidate.badge_log:
                logs.append((candidate.username, entry))
        logs.sort(key=lambda row: row[1].timestamp, reverse=True)
        rows = "".join(
            f"<tr><td>{self._fmt_date(entry.date)}</td><td>{self._e(entry.username)}</td><td>{self._e(entry.planned_at)}</td><td>{'In sede' if entry.in_office else 'Telelavoro'}</td><td>{self._schedule_cell(entry.badge_in_at, entry.skip_badge_in, entry.badge_in_executed)}</td><td>{self._schedule_cell(entry.badge_out_at, entry.skip_badge_out, entry.badge_out_executed)}</td><td>{self._e(entry.note or '-')}</td><td>{self._schedule_delete_form(entry)}</td></tr>"
            for entry in schedules
            if user.is_admin or entry.user_id == user.id
        ) or "<tr><td colspan='8'>Nessuna pianificazione disponibile.</td></tr>"
        log_rows = "".join(
            f"<tr><td>{self._e(log.timestamp)}</td><td>{self._e(username)}</td><td>{self._e(log.type)}</td><td>{'OK' if log.success else 'KO'}</td><td>{self._e(log.note)}</td></tr>"
            for username, log in logs[:30]
        ) or "<tr><td colspan='5'>Nessun evento disponibile.</td></tr>"
        cancel = "" if user.is_admin else "<form method='post' action='/pauses/cancel-today'><button class='danger'>Skippa le pianificazioni odierne</button></form>"
        body = f"{self._msg(message)}<div class='card hero'><h1>Dashboard</h1><p class='muted'>Pianificazioni e ultimi eventi badge.</p><div class='actions'><form method='post' action='/dashboard/scheduler/replan'><button class='alt'>Aggiorna pianificazione</button></form>{cancel}</div></div><div class='card table'><h2>Pianificazioni presenti</h2><table><thead><tr><th>Data</th><th>Utente</th><th>Elaborata</th><th>Modalita</th><th>Badge IN</th><th>Badge OUT</th><th>Note</th><th>Azioni</th></tr></thead><tbody>{rows}</tbody></table></div><div class='card table'><h2>Ultimi 30 eventi</h2><table><thead><tr><th>Data/Ora</th><th>Utente</th><th>Tipo</th><th>Esito</th><th>Note</th></tr></thead><tbody>{log_rows}</tbody></table></div>"
        return self._page("Dashboard", body, user)

    def _settings_page(self, user: UserProfile, message: str) -> str:
        day_labels = ["Lun", "Mar", "Mer", "Gio", "Ven"]
        checks = "".join(f"<label class='check'><input type='checkbox' name='office_day' value='{idx}' {'checked' if idx in user.office_days else ''}> {label}</label>" for idx, label in enumerate(day_labels))
        body = f"""{self._msg(message)}<form method="post"><div class="card hero"><h1>Impostazioni utente</h1></div>
<div class="card"><h2>Casa</h2><div class="grid"><label>Latitudine casa<input name="home_lat" value="{user.home_lat:.6f}"></label><label>Longitudine casa<input name="home_lon" value="{user.home_lon:.6f}"></label><label>Accuratezza casa<input name="home_accuracy" value="{user.home_accuracy}"></label></div></div>
<div class="card"><h2>Ufficio</h2><div class="grid"><label>Latitudine sede<input name="office_lat" value="{user.office_lat:.6f}"></label><label>Longitudine sede<input name="office_lon" value="{user.office_lon:.6f}"></label><label>Accuratezza sede<input name="office_accuracy" value="{user.office_accuracy}"></label></div></div>
<div class="card"><h2>Giorni in ufficio</h2><div class="checkrow">{checks}</div></div>
<div class="card"><h2>Notifiche ntfy</h2><label class="check"><input type="checkbox" name="ntfy_enabled" {'checked' if user.ntfy_enabled else ''}> Abilita notifiche ntfy</label><label>Topic<input name="ntfy_topic" value="{self._e(user.ntfy_topic)}"></label><div class="actions"><button name="submit_action" value="save">Salva</button><button class="alt" name="submit_action" value="test_ntfy">Testa notifiche</button></div></div></form>"""
        return self._page("Impostazioni", body, user)

    def _pauses_page(self, user: UserProfile, message: str) -> str:
        pauses = "".join(f"<tr><td>{self._fmt_date(pause)}</td><td><a class='btn danger' href='/pauses/delete?date={quote(pause)}'>Rimuovi</a></td></tr>" for pause in user.scheduled_pauses) or "<tr><td colspan='2'>Nessuna pausa configurata.</td></tr>"
        body = f"{self._msg(message)}<div class='card hero'><h1>Pause</h1><p class='muted'>Date in cui lo scheduler salta l'automazione per il tuo profilo.</p></div><div class='split'><div class='card table'><h2>Pause configurate</h2><table><tbody>{pauses}</tbody></table></div><div class='card'><h2>Nuova pausa</h2><form method='post' action='/pauses/add'><label>Data<input type='date' name='date' required></label><div class='actions'><button>Aggiungi pausa</button></div></form></div></div>"
        return self._page("Pause", body, user)

    def _diagnostics_page(self, user: UserProfile, message: str) -> str:
        schedules = self.scheduler_manager.get_schedules_snapshot()
        options = "".join(f"<option value='{candidate.id}'>{self._e(candidate.username)}</option>" for candidate in self.user_manager.get_corem_enabled_users())
        schedule_rows = "".join(f"<tr><td>{self._fmt_date(entry.date)}</td><td>{self._e(entry.username)}</td><td>{self._e(entry.note or '-')}</td><td><form method='post' action='/admin/scheduler/delete'><input type='hidden' name='date' value='{self._e(entry.date)}'><input type='hidden' name='user_id' value='{entry.user_id}'><button class='danger'>Cancella</button></form></td></tr>" for entry in schedules) or "<tr><td colspan='4'>Nessuna pianificazione presente.</td></tr>"
        body = f"{self._msg(message)}<div class='card'><h2>Pianificazione manuale</h2><form method='post' action='/admin/scheduler/replan'><div class='grid'><label>Data<input type='date' name='date' value='{self.ntp_manager.get_current_date()}'></label><label>Utente<select name='user_id'><option value='0'>Tutti gli utenti Corem</option>{options}</select></label></div><div class='actions'><button class='alt'>Avvia pianificazione</button></div></form></div><div class='card table'><h2>Pianificazioni salvate</h2><table><thead><tr><th>Data</th><th>Utente</th><th>Note</th><th>Azioni</th></tr></thead><tbody>{schedule_rows}</tbody></table></div>"
        return self._page("Diagnostica", body, user)

    def _admin_page(self, user: UserProfile, message: str) -> str:
        ntfy = self.notification_manager.get_settings()
        scheduler = self.scheduler_manager.get_settings()
        users = self.user_manager.get_all_users()
        user_rows = ""
        for candidate in users:
            delete_link = "" if candidate.is_admin else f" | <a href='/admin/delete?id={candidate.id}'>Elimina</a>"
            role = "Admin" if candidate.is_admin else "User"
            user_rows += f"<tr><td>{candidate.id}</td><td>{self._e(candidate.username)}</td><td>{role}</td><td><a href='/admin/user?id={candidate.id}'>Modifica</a>{delete_link}</td></tr>"
        body = f"""{self._msg(message)}<div class="card hero"><h1>Admin</h1><p class="muted">Gestione utenti, notifiche e scheduler.</p></div>
<div class="card"><h2>Notifiche ntfy</h2><form method="post" action="/admin/ntfy"><label class="check"><input type="checkbox" name="enabled" {'checked' if ntfy.enabled else ''}> Abilita supporto ntfy</label><div class="grid"><label>Server<input name="base_url" value="{self._e(ntfy.base_url)}"></label><label>Topic test globale<input name="topic" value="{self._e(ntfy.topic)}"></label><label>Token<input name="access_token" value="{self._e(ntfy.access_token)}"></label></div><div class="actions"><button name="submit_action" value="save">Salva notifiche</button><button class="alt" name="submit_action" value="test_ntfy">Testa notifiche</button></div></form></div>
<div class="card"><h2>Scheduler</h2><form method="post" action="/admin/scheduler/settings"><label class="check"><input type="checkbox" name="auto_startup_enabled" {'checked' if scheduler.auto_startup_enabled else ''}> Pianifica allo startup</label><div class="grid"><label>Ora automatica<input name="auto_time" value="{self._e(scheduler.auto_time)}"></label><label>% orario puntuale<input name="exact_badge_chance_percent" value="{scheduler.exact_badge_chance_percent}"></label><label>% offset vicino<input name="near_badge_offset_chance_percent" value="{scheduler.near_badge_offset_chance_percent}"></label></div><div class="actions"><button>Salva scheduler</button></div></form></div>
<div class="card table"><h2>Utenti</h2><div class="actions"><a class="btn" href="/admin/user">Nuovo utente</a></div><table><thead><tr><th>ID</th><th>Username</th><th>Ruolo</th><th>Azioni</th></tr></thead><tbody>{user_rows}</tbody></table></div>"""
        return self._page("Admin", body, user)

    def _admin_user_page(self, current: UserProfile, editing: UserProfile | None, message: str) -> str:
        target = editing or UserProfile()
        is_edit = editing is not None
        body = f"""{self._msg(message)}<form method="post"><input type="hidden" name="id" value="{target.id}">
<div class="card hero"><h1>{'Modifica utente' if is_edit else 'Nuovo utente'}</h1></div><div class="split"><div class="card"><h2>Accesso web</h2><label>Username<input name="username" value="{self._e(target.username)}" required></label><label>Password<input type="password" name="password" placeholder="{'Lascia vuoto per non cambiare' if is_edit else 'Password utente'}"></label><label class="check"><input type="checkbox" name="is_admin" {'checked' if target.is_admin else ''}> Utente admin</label></div>
<div class="card"><h2>Corem</h2><label>Username Corem<input name="corem_username" value="{self._e(target.corem_username)}"></label><label>Password Corem<input type="password" name="corem_password" value="{self._e(target.corem_password)}"></label><label>ID utente Corem<input name="corem_user_id" value="{target.corem_user_id}"></label><label class="check"><input type="checkbox" name="ntfy_enabled" {'checked' if target.ntfy_enabled else ''}> Abilita ntfy</label><label>Topic ntfy<input name="ntfy_topic" value="{self._e(target.ntfy_topic)}"></label></div></div><div class="card actions"><button name="submit_action" value="save">Salva utente</button>{'<button class="alt" name="submit_action" value="test_ntfy">Testa notifiche</button>' if is_edit else ''}<a class="btn" href="/admin">Torna ad admin</a></div></form>"""
        return self._page("Utente", body, current)

    def _schedule_delete_form(self, entry: DailyScheduleSnapshot) -> str:
        return f"<form method='post' action='/dashboard/scheduler/delete'><input type='hidden' name='date' value='{self._e(entry.date)}'><input type='hidden' name='user_id' value='{entry.user_id}'><button class='danger iconbtn' title='Cancella'>X</button></form>"

    def _find_user_by_username(self, username: str) -> UserProfile | None:
        return next((user for user in self.user_manager.get_all_users() if user.username == username), None)

    def _with_msg(self, endpoint: str, message: str, **values: object) -> str:
        base = url_for(endpoint, **values)
        return f"{base}?msg={quote(message)}"

    def _msg(self, message: str) -> str:
        return f"<div class='msg'>{self._e(message)}</div>" if message else ""

    @staticmethod
    def _e(value: object) -> str:
        return html.escape(str(value), quote=True)

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

    @staticmethod
    def _schedule_cell(epoch: float, skipped: bool, executed: bool) -> str:
        if skipped:
            return "Skip"
        value = datetime_from_epoch(epoch)
        return f"{value} (eseguito)" if executed else value


def datetime_from_epoch(epoch: float) -> str:
    if epoch <= 0:
        return "-"
    from datetime import datetime

    return datetime.fromtimestamp(epoch).strftime("%d/%m/%Y %H:%M:%S")
