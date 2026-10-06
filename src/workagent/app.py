"""Composition root. Wires config, vault, collector, context engine, reports, agent and scheduler,
and exposes them to the UI through Qt signals. The only module that knows all the others.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .agent.agent import AgentAnswer, WorkAgent
from .ai import opencode
from .ai.providers import (PROVIDERS, AIProvider, AIProviderError, build_provider, create_provider,
                           model_for, spec_for)
from .config import Config
from .context.extractor import ContextExtractor
from .context.sessions import DaySummary, summarize_day
from .models import Activity, Report, Task
from .reports.generator import ReportGenerator, compose_with_llm, polish_with_llm
from .scheduler import Scheduler
from .storage.repositories import ActivityRepository, ReportRepository, SecretRepository, TaskRepository
from .storage.vault import Vault, VaultState
from .system import startup
from .tracking.browser import BrowserUrlReader
from .tracking.coalescer import Coalescer
from .tracking.collector import Collector, TrackingMode
from .tracking.privacy import PrivacyFilter

log = logging.getLogger(__name__)

AI_KEY_SECRET = "ai_api_key"   # legacy single key (v0.1)
AI_KEY_PREFIX = "ai_key:"


class AppController(QObject):
    tracking_changed = Signal(str)        # TrackingMode value
    vault_changed = Signal(str)           # VaultState value
    activity_changed = Signal(object)     # current Activity | None (already privacy-filtered)
    data_changed = Signal()               # something was persisted
    report_ready = Signal(str, object)    # day, Report (saved drafts are also in the vault)
    agent_answer = Signal(object)         # AgentAnswer
    notify = Signal(str, str)             # title, message (tray balloon)
    ui_mode_changed = Signal(str)         # "desktop" | "web"
    _main_call = Signal(object)           # internal: run a callable on the Qt thread

    def __init__(self, config: Config, config_path: Path, vault: Vault):
        super().__init__()
        self.config = config
        self._config_path = config_path
        self.vault = vault
        self.activities = ActivityRepository(vault)
        self.reports = ReportRepository(vault)
        self.tasks = TaskRepository(vault)
        self.secrets = SecretRepository(vault)
        self.generator = ReportGenerator(config.report)
        self._privacy = PrivacyFilter(config.privacy)
        self._current: Activity | None = None
        self._idle = 0.0
        self._session_locked = False
        self._collector: Collector | None = None
        self._coalescer: Coalescer | None = None
        self._probe_error = ""
        self.scheduler = Scheduler(config.report.time, config.report.auto_generate,
                                   config.security.auto_lock_idle_minutes)
        self.agent = WorkAgent(
            load_day=self._safe_day, load_tasks=self._safe_tasks,
            current_activity=lambda: self._current, generator=self.generator,
            provider=self.ai_provider, llm_allowed=lambda: self.config.ai.allow_chat)
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._tick)
        self._main_call.connect(self._run_main_call)

    # --- threading --------------------------------------------------------------------------

    def run_on_main(self, fn, timeout: float = 60.0):
        """Run `fn` on the Qt thread and return its result (for callers like the web server)."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        done = threading.Event()
        box: dict = {}

        def job() -> None:
            try:
                box["result"] = fn()
            except BaseException as exc:  # noqa: BLE001 - re-raised in the calling thread
                box["error"] = exc
            finally:
                done.set()

        self._main_call.emit(job)
        if not done.wait(timeout):
            raise TimeoutError("main thread did not respond")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    @staticmethod
    def _run_main_call(job) -> None:
        job()

    # --- lifecycle --------------------------------------------------------------------------

    def start(self) -> None:
        if self.vault.state is not VaultState.UNINITIALIZED:
            self._start_collector()
        self._timer.start()

    def shutdown(self) -> None:
        self._timer.stop()
        if self._collector is not None:
            self._collector.stop()
        self.vault.close()
        log.info("shutdown complete")

    def _start_collector(self) -> None:
        if self._collector is not None:
            return
        if sys.platform != "win32":
            self._probe_error = "Activity tracking requires Windows."
            log.warning("tracking disabled: not on Windows")
            return
        from .tracking.win32 import Win32Probe

        t = self.config.tracking
        self._coalescer = coalescer = Coalescer(self._extractor(), idle_seconds=t.idle_seconds,
                              min_activity_seconds=t.min_activity_seconds, flush_seconds=t.flush_seconds,
                              max_gap_seconds=max(30.0, t.sample_seconds * 10))
        self._collector = Collector(Win32Probe(), self._privacy, coalescer, self._persist,
                                    interval=t.sample_seconds, url_reader=self._url_reader(),
                                    on_sample=self._on_sample)
        if t.start_paused:
            self._collector.set_mode(TrackingMode.PAUSED)
        self._collector.start()
        self.tracking_changed.emit(self._collector.mode.value)

    def _extractor(self) -> ContextExtractor:
        i = self.config.integrations
        return ContextExtractor(i.ticket_projects, i.project_rules)

    def _url_reader(self) -> BrowserUrlReader | None:
        if self.config.privacy.browser_url_mode == "off":
            return None
        reader = BrowserUrlReader()
        return reader if reader.available else None

    # --- collector callbacks (collector thread) ---------------------------------------------

    def _persist(self, activity: Activity) -> None:
        self.activities.upsert(activity)
        self.data_changed.emit()

    def _on_sample(self, session_locked: bool, idle: float, current: Activity | None) -> None:
        self._idle = idle
        changed = (current is None) != (self._current is None) or (
            current is not None and self._current is not None
            and (current.id != self._current.id or current.kind != self._current.kind))
        self._current = current
        if changed:
            self.activity_changed.emit(current)
        if session_locked and not self._session_locked and self.config.security.lock_on_windows_lock:
            self.lock()
        self._session_locked = session_locked

    # --- tracking ---------------------------------------------------------------------------

    @property
    def tracking_mode(self) -> TrackingMode:
        return self._collector.mode if self._collector else TrackingMode.PAUSED

    @property
    def tracking_error(self) -> str:
        return self._probe_error

    @property
    def tracking_started(self) -> bool:
        return self._collector is not None

    @property
    def current_activity(self) -> Activity | None:
        return self._current

    def set_tracking_mode(self, mode: TrackingMode) -> None:
        if self._collector is None:
            return
        self._collector.set_mode(mode)
        self.tracking_changed.emit(mode.value)

    # --- vault ------------------------------------------------------------------------------

    def setup_vault(self, pin: str, run_at_startup: bool) -> None:
        self.vault.initialize(pin)
        self.config.run_at_startup = run_at_startup
        self.save_config()
        self._apply_startup()
        self._start_collector()
        self.vault_changed.emit(self.vault.state.value)

    def unlock(self, pin: str) -> int:
        migrated = self.vault.unlock(pin)
        self.vault_changed.emit(self.vault.state.value)
        self.data_changed.emit()
        QTimer.singleShot(500, self._tick)  # catch up on report drafts
        return migrated

    def lock(self) -> None:
        if self.vault.is_unlocked:
            self.vault.lock()
            self.vault_changed.emit(self.vault.state.value)

    def change_pin(self, old: str, new: str) -> None:
        self.vault.change_pin(old, new)

    # --- data access (UI thread, unlocked only) ---------------------------------------------

    def _safe_day(self, day: str) -> list[Activity]:
        return self.activities.list_day(day) if self.vault.is_unlocked else []

    def _safe_tasks(self) -> list[Task]:
        return self.tasks.list() if self.vault.is_unlocked else []

    def day_activities(self, day: str) -> list[Activity]:
        acts = self._safe_day(day)
        cur = self._current
        # Show the open activity live, even before its first flush.
        if cur is not None and cur.day == day and self.vault.is_unlocked:
            acts = [a for a in acts if a.id != cur.id] + [cur]
            acts.sort(key=lambda a: a.start)
        return acts

    def day_summary(self, day: str) -> DaySummary:
        return summarize_day(day, self.day_activities(day))

    # --- reports ----------------------------------------------------------------------------

    def generate_report(self, day: str, use_llm: bool | None = None) -> Report:
        acts = self.day_activities(day)
        report = self.generator.generate(day, acts, self._safe_tasks())
        ai = self.config.ai
        allow = ai.allow_reports if use_llm is None else (use_llm and ai.allow_reports)
        if not allow or spec_for(ai.provider).kind == "none" or not self.vault.is_unlocked:
            return report
        try:
            provider = create_provider(ai, ai.provider, self.ai_key(ai.provider))
        except AIProviderError as exc:
            report.ai_error = str(exc)
            return report
        if ai.report_mode == "polish":
            return polish_with_llm(report, provider, acts)
        return compose_with_llm(report, provider, acts, self._safe_tasks(), ai.report_language)

    def generate_report_async(self, day: str, save: bool, announce: bool = False) -> None:
        def work() -> None:
            try:
                report = self.generate_report(day)
                if save and self.vault.is_unlocked:
                    self.reports.save(report)
                self.report_ready.emit(day, report)
                if announce:
                    self.notify.emit("Báo cáo ngày", f"Bản nháp báo cáo ngày {day} đã sẵn sàng để xem lại.")
            except Exception:  # noqa: BLE001
                log.exception("report generation failed")
        threading.Thread(target=work, name="report", daemon=True).start()

    # --- agent ------------------------------------------------------------------------------

    def ask_agent_async(self, question: str) -> None:
        def work() -> None:
            try:
                answer = self.agent.ask(question, date.today())
            except Exception:  # noqa: BLE001
                log.exception("agent failed")
                answer = AgentAnswer("Xin lỗi, đã có lỗi khi trả lời câu hỏi này.")
            self.agent_answer.emit(answer)
        threading.Thread(target=work, name="agent", daemon=True).start()

    def ai_provider(self) -> AIProvider | None:
        if self.config.ai.provider == "none" or not self.vault.is_unlocked:
            return None
        return build_provider(self.config.ai, self.ai_key)

    # --- AI keys / models (keys live in the vault, one per provider) --------------------------

    def ai_key(self, provider: str) -> str:
        if not self.vault.is_unlocked:
            return ""
        key = self.secrets.get(AI_KEY_PREFIX + provider)
        if not key and provider == self.config.ai.provider:
            key = self.secrets.get(AI_KEY_SECRET)  # single key saved by v0.1
        return key

    def set_ai_key(self, provider: str, key: str) -> None:
        if provider in PROVIDERS and PROVIDERS[provider].kind != "none":
            self.secrets.set(AI_KEY_PREFIX + provider, key.strip())

    def ai_keys_set(self) -> dict[str, bool]:
        return {p: bool(self.ai_key(p)) for p in PROVIDERS}

    def ai_list_models(self, provider: str, base_url: str | None = None, api_key: str | None = None) -> list[str]:
        """Live model list from the provider (network call — run off the UI thread)."""
        spec = spec_for(provider)
        if spec.kind == "opencode":
            return opencode.list_models(self.config.ai.opencode_path)
        client = create_provider(self.config.ai, provider, api_key or self.ai_key(provider), model="",
                                 base_url=base_url)
        return client.list_models()

    def ai_test(self, provider: str, model: str, base_url: str | None = None,
                api_key: str | None = None) -> tuple[str, float]:
        """Send a fixed, data-free prompt; returns (reply, seconds). Raises AIProviderError."""
        client = create_provider(self.config.ai, provider, api_key or self.ai_key(provider),
                                 model=model or model_for(self.config.ai, provider), base_url=base_url)
        started = time.monotonic()
        reply = client.complete("You are a connectivity check.", "Reply with exactly: OK")
        return reply.strip()[:200], time.monotonic() - started

    # --- config -----------------------------------------------------------------------------

    def save_config(self) -> None:
        self.config.save(self._config_path)

    def apply_config(self, config: Config) -> None:
        old_mode = self.config.ui_mode
        self.config = config
        self.save_config()
        self._privacy.update(config.privacy)
        self.generator = ReportGenerator(config.report)
        self.agent._generator = self.generator  # noqa: SLF001 - same composition root
        self.scheduler.report_time = config.report.time
        self.scheduler.auto_report = config.report.auto_generate
        self.scheduler.auto_lock_idle_minutes = config.security.auto_lock_idle_minutes
        if self._collector is not None:
            self._collector.set_url_reader(self._url_reader())
        if self._coalescer is not None:
            self._coalescer.set_extractor(self._extractor())
        self._apply_startup()
        logging.getLogger().setLevel(logging.DEBUG if config.debug else logging.INFO)
        log.info("settings applied (tracking interval/idle changes apply after restart)")
        if config.ui_mode != old_mode:
            self.ui_mode_changed.emit(config.ui_mode)

    def _apply_startup(self) -> None:
        if getattr(sys, "frozen", False) or not self.config.run_at_startup:
            startup.set_enabled(self.config.run_at_startup)
        elif self.config.run_at_startup and not startup.is_enabled():
            log.info("dev run: not registering startup automatically (use the built .exe)")

    # --- scheduler --------------------------------------------------------------------------

    def _tick(self) -> None:
        actions = self.scheduler.tick(datetime.now(), self._idle, self.vault.is_unlocked,
                                      has_report=lambda d: self.reports.get(d) is not None)
        for day in actions.generate_reports:
            if self._safe_day(day):
                self.generate_report_async(day, save=True, announce=True)

        if actions.lock_vault:
            log.info("auto-lock after idle")
            self.lock()
