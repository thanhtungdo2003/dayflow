"""JSON API for the web UI. Transport-independent: `handle()` takes a parsed request and returns
(status, payload), so it is tested without sockets. All calls go through the AppController;
anything that touches Qt objects is marshalled to the Qt thread with `run_on_main`.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime
from typing import Any

from .. import __version__
from ..ai.opencode import find_opencode
from ..ai.providers import PROVIDERS, AIProviderError, model_for
from ..app import AppController
from ..config import Config
from ..context.sessions import summarize_day
from ..integrations.jira import time_by_ticket
from ..models import TASK_STATUSES, Report, Task, new_id
from ..storage.vault import MIN_PIN_LENGTH, VaultError, VaultLockedError, WeakPinError, WrongPinError
from ..tracking.collector import TrackingMode

log = logging.getLogger(__name__)

Response = tuple[int, Any]


class ApiError(Exception):
    def __init__(self, status: int, code: str, extra: dict | None = None):
        super().__init__(code)
        self.status, self.code, self.extra = status, code, extra or {}


def _day(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ApiError(400, "bad_date") from exc


class _PinGuard:
    """Online guessing throttle (offline guessing is bounded by Argon2id)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures = 0
        self._blocked_until = 0.0

    def check(self) -> None:
        with self._lock:
            remaining = self._blocked_until - time.monotonic()
        if remaining > 0:
            raise ApiError(429, "too_many_attempts", {"retry_after": int(remaining) + 1})

    def failed(self) -> int:
        with self._lock:
            self._failures += 1
            delay = 0 if self._failures < 3 else min(300, 2 ** (self._failures - 2))
            self._blocked_until = time.monotonic() + delay
            return delay

    def succeeded(self) -> None:
        with self._lock:
            self._failures, self._blocked_until = 0, 0.0


class WebApi:
    def __init__(self, ctrl: AppController):
        self.ctrl = ctrl
        self._pins = _PinGuard()
        self._routes = {
            ("GET", "/api/state"): self.state,
            ("POST", "/api/setup"): self.setup,
            ("POST", "/api/unlock"): self.unlock,
            ("POST", "/api/lock"): self.lock,
            ("POST", "/api/tracking"): self.tracking,
            ("GET", "/api/day"): self.day,
            ("DELETE", "/api/day"): self.delete_day,
            ("GET", "/api/tasks"): self.tasks,
            ("POST", "/api/tasks"): self.save_task,
            ("DELETE", "/api/tasks"): self.delete_task,
            ("GET", "/api/tickets"): self.tickets,
            ("POST", "/api/agent"): self.agent,
            ("GET", "/api/report"): self.report,
            ("POST", "/api/report/generate"): self.generate_report,
            ("PUT", "/api/report"): self.save_report,
            ("GET", "/api/settings"): self.settings,
            ("PUT", "/api/settings"): self.save_settings,
            ("POST", "/api/pin"): self.change_pin,
            ("GET", "/api/ai"): self.ai_info,
            ("POST", "/api/ai/models"): self.ai_models,
            ("POST", "/api/ai/test"): self.ai_test,
        }

    def handle(self, method: str, path: str, query: dict[str, str], body: dict[str, Any]) -> Response:
        route = self._routes.get((method, path))
        if route is None:
            return 404, {"error": "not_found"}
        try:
            return 200, route(query, body)
        except ApiError as exc:
            return exc.status, {"error": exc.code, **exc.extra}
        except VaultLockedError:
            return 423, {"error": "locked"}
        except Exception:  # noqa: BLE001 - never leak internals to the client
            log.exception("web api error on %s %s", method, path)
            return 500, {"error": "internal"}

    def _require_unlocked(self) -> None:
        if not self.ctrl.vault.is_unlocked:
            raise VaultLockedError("locked")

    # --- state / vault ----------------------------------------------------------------------

    def state(self, query, body) -> dict:
        c = self.ctrl
        unlocked = c.vault.is_unlocked
        cur = c.current_activity if unlocked else None
        return {
            "version": __version__,
            "vault": c.vault.state.value,
            "tracking": c.tracking_mode.value,
            "tracking_started": c.tracking_started,
            "tracking_error": c.tracking_error,
            "pending": c.vault.pending_writes() if c.vault.state.value == "locked" else 0,
            "ui_mode": c.config.ui_mode,
            "ai": {"provider": c.config.ai.provider, "chat": c.config.ai.allow_chat,
                   "reports": c.config.ai.allow_reports},
            "current": cur.to_dict() if cur else None,
            "min_pin": MIN_PIN_LENGTH,
        }

    def setup(self, query, body) -> dict:
        pin = str(body.get("pin", ""))
        if len(pin) < MIN_PIN_LENGTH:
            raise ApiError(400, "weak_pin")
        try:
            self.ctrl.run_on_main(lambda: self.ctrl.setup_vault(pin, bool(body.get("run_at_startup", True))))
        except WeakPinError as exc:
            raise ApiError(400, "weak_pin") from exc
        except VaultError as exc:
            raise ApiError(409, "already_initialized") from exc
        return {"ok": True}

    def unlock(self, query, body) -> dict:
        self._pins.check()
        try:
            migrated = self.ctrl.run_on_main(lambda: self.ctrl.unlock(str(body.get("pin", ""))))
        except WrongPinError as exc:
            delay = self._pins.failed()
            raise ApiError(403, "wrong_pin", {"retry_after": delay}) from exc
        self._pins.succeeded()
        return {"ok": True, "migrated": migrated}

    def lock(self, query, body) -> dict:
        self.ctrl.run_on_main(self.ctrl.lock)
        return {"ok": True}

    def tracking(self, query, body) -> dict:
        try:
            mode = TrackingMode(body.get("mode"))
        except ValueError as exc:
            raise ApiError(400, "bad_mode") from exc
        self.ctrl.run_on_main(lambda: self.ctrl.set_tracking_mode(mode))
        return {"ok": True, "tracking": self.ctrl.tracking_mode.value}

    def change_pin(self, query, body) -> dict:
        self._pins.check()
        try:
            self.ctrl.change_pin(str(body.get("old", "")), str(body.get("new", "")))
        except WrongPinError as exc:
            self._pins.failed()
            raise ApiError(403, "wrong_pin") from exc
        except WeakPinError as exc:
            raise ApiError(400, "weak_pin") from exc
        self._pins.succeeded()
        return {"ok": True}

    # --- activity ---------------------------------------------------------------------------

    def day(self, query, body) -> dict:
        self._require_unlocked()
        day = _day(query.get("date"))
        acts = self.ctrl.day_activities(day)
        s = summarize_day(day, acts)
        return {
            "date": day,
            "summary": {
                "active": s.active_seconds, "private": s.private_seconds, "away": s.away_seconds,
                "first": s.first_ts, "last": s.last_ts, "longest": s.longest_session_seconds,
                "by_category": s.by_category, "by_app": s.by_app, "by_project": s.by_project,
                "by_ticket": s.by_ticket,
            },
            "sessions": [{
                "start": x.start, "end": x.end, "label": x.label, "project": x.project,
                "top_app": x.top_app, "tickets": x.tickets[:5], "active": x.active_seconds,
                "ids": [a.id for a in x.activities],
            } for x in s.sessions],
            "activities": [a.to_dict() for a in acts],
            "day_start": datetime.strptime(day, "%Y-%m-%d").timestamp(),
        }

    def delete_day(self, query, body) -> dict:
        self._require_unlocked()
        return {"deleted": self.ctrl.activities.delete_day(_day(query.get("date")))}

    # --- tasks ------------------------------------------------------------------------------

    def tasks(self, query, body) -> dict:
        self._require_unlocked()
        tracked = time_by_ticket(self.ctrl.activities.list_range(date.today(), 7))
        return {"tasks": [{**t.to_dict(), "tracked": tracked.get(t.ticket, 0.0)} for t in self.ctrl.tasks.list()],
                "jira": self.ctrl.config.integrations.jira_base_url}

    def save_task(self, query, body) -> dict:
        self._require_unlocked()
        title = str(body.get("title", "")).strip()[:300]
        status = body.get("status", "todo")
        if not title or status not in TASK_STATUSES:
            raise ApiError(400, "bad_task")
        existing = {t.id: t for t in self.ctrl.tasks.list()}
        task = existing.get(str(body.get("id", ""))) or Task(id=new_id(), title=title)
        if status == "done" and task.status != "done":
            task.done_at = time.time()
        elif status != "done":
            task.done_at = None
        task.title, task.status = title, status
        task.ticket = str(body.get("ticket", "")).strip().upper()[:40]
        task.project = str(body.get("project", "")).strip()[:120]
        task.notes = str(body.get("notes", "")).strip()[:4000]
        task.needs_support = bool(body.get("needs_support", False))
        task.updated_at = time.time()
        self.ctrl.tasks.save(task)
        return {"task": task.to_dict()}

    def delete_task(self, query, body) -> dict:
        self._require_unlocked()
        self.ctrl.tasks.delete(str(query.get("id", "")))
        return {"ok": True}

    def tickets(self, query, body) -> dict:
        self._require_unlocked()
        tracked = time_by_ticket(self.ctrl.activities.list_range(date.today(), 7))
        known = {t.ticket for t in self.ctrl.tasks.list()}
        return {"tickets": [{"ticket": k, "seconds": v, "has_task": k in known}
                            for k, v in sorted(tracked.items(), key=lambda kv: -kv[1])]}

    # --- agent / reports --------------------------------------------------------------------

    def agent(self, query, body) -> dict:
        self._require_unlocked()
        answer = self.ctrl.agent.ask(str(body.get("question", ""))[:1000], date.today())
        return {"text": answer.text, "used_llm": answer.used_llm, "shared": answer.shared_items}

    def report(self, query, body) -> dict:
        self._require_unlocked()
        report = self.ctrl.reports.get(_day(query.get("date")))
        return {"report": report.to_dict() if report else None}

    def generate_report(self, query, body) -> dict:
        self._require_unlocked()
        return {"report": self.ctrl.generate_report(_day(body.get("date"))).to_dict()}

    def save_report(self, query, body) -> dict:
        self._require_unlocked()
        day = _day(body.get("date"))
        markdown = str(body.get("markdown", ""))[:200_000]
        if isinstance(body.get("generated"), dict):  # a fresh draft replaces the stored report
            report = Report.from_dict({**body["generated"], "day": day, "edited": False})
        else:
            report = self.ctrl.reports.get(day)
        if report is None:
            report = Report(day=day, generated_at=time.time(), sections={})
        if markdown != report.markdown:
            report.edited = True
        report.markdown = markdown
        self.ctrl.reports.save(report)
        return {"report": report.to_dict()}

    # --- settings ---------------------------------------------------------------------------

    def settings(self, query, body) -> dict:
        self._require_unlocked()
        return {"config": self.ctrl.config.to_dict(), "keys_set": self.ctrl.ai_keys_set()}

    def save_settings(self, query, body) -> dict:
        self._require_unlocked()
        incoming = body.get("config")
        if not isinstance(incoming, dict):
            raise ApiError(400, "bad_config")
        merged = self.ctrl.config.to_dict()
        for key, value in incoming.items():
            if isinstance(merged.get(key), dict) and isinstance(value, dict):
                merged[key].update(value)
            elif key in merged:
                merged[key] = value
        config = Config.from_dict(merged)
        ai = config.ai
        valid = (config.ui_mode in ("desktop", "web") and ai.provider in PROVIDERS
                 and ai.report_mode in ("compose", "polish") and ai.report_language in ("vi", "en")
                 and config.privacy.browser_url_mode in ("off", "domain", "full")
                 and 1024 <= config.web_port <= 65535 and _valid_opencode_path(ai.opencode_path))
        if not valid:
            raise ApiError(400, "bad_config")
        keys = body.get("api_keys") or {}
        if not isinstance(keys, dict):
            raise ApiError(400, "bad_config")
        if body.get("api_key"):  # v0.1 clients: key for the selected provider
            keys.setdefault(ai.provider, body["api_key"])
        for provider, key in keys.items():
            if provider in PROVIDERS and key is not None:
                self.ctrl.set_ai_key(provider, str(key)[:500])
        self.ctrl.run_on_main(lambda: self.ctrl.apply_config(config))
        return {"ok": True, "config": config.to_dict()}

    # --- AI providers -----------------------------------------------------------------------

    def ai_info(self, query, body) -> dict:
        self._require_unlocked()
        keys = self.ctrl.ai_keys_set()
        exe = find_opencode(self.ctrl.config.ai.opencode_path)
        return {"providers": [{**spec.to_dict(), "key_set": keys.get(spec.id, False),
                               "model": model_for(self.ctrl.config.ai, spec.id)} for spec in PROVIDERS.values()],
                "opencode": {"found": bool(exe), "path": exe}}

    def _ai_args(self, body) -> tuple[str, str | None, str | None]:
        provider = str(body.get("provider", ""))
        if provider not in PROVIDERS or PROVIDERS[provider].kind == "none":
            raise ApiError(400, "bad_provider")
        base_url = str(body["base_url"]).strip() if body.get("base_url") else None
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ApiError(400, "bad_url")
        api_key = str(body["api_key"]).strip() if body.get("api_key") else None
        return provider, base_url, api_key

    def ai_models(self, query, body) -> dict:
        self._require_unlocked()
        provider, base_url, api_key = self._ai_args(body)
        try:
            return {"models": self.ctrl.ai_list_models(provider, base_url, api_key)}
        except AIProviderError as exc:
            raise ApiError(502, "provider", {"message": str(exc)}) from exc

    def ai_test(self, query, body) -> dict:
        self._require_unlocked()
        provider, base_url, api_key = self._ai_args(body)
        try:
            reply, seconds = self.ctrl.ai_test(provider, str(body.get("model", "")).strip(), base_url, api_key)
        except AIProviderError as exc:
            raise ApiError(502, "provider", {"message": str(exc)}) from exc
        return {"ok": True, "reply": reply, "seconds": round(seconds, 1)}


def _valid_opencode_path(path: str) -> bool:
    """Only an OpenCode binary may be configured (the web API must not become 'run any program')."""
    if not path:
        return True
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name in ("opencode", "opencode.exe")
