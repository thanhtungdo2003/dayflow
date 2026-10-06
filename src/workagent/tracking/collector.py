"""Background collector thread: probe -> privacy filter -> coalescer -> sink.

The collector never touches Qt. It reports through plain callbacks, which the AppController
bridges to Qt signals.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Callable, Protocol

from ..models import Activity
from .coalescer import Coalescer, Observation
from .privacy import PrivacyFilter
from .win32 import WindowSample

log = logging.getLogger(__name__)


class TrackingMode(Enum):
    TRACKING = "tracking"
    PAUSED = "paused"
    PRIVACY = "privacy"


class Probe(Protocol):
    def sample(self) -> WindowSample: ...


class UrlReader(Protocol):
    def read(self, hwnd: int, app: str, title: str) -> str: ...


class Collector:
    def __init__(self, probe: Probe, privacy: PrivacyFilter, coalescer: Coalescer,
                 sink: Callable[[Activity], None], interval: float = 2.0,
                 url_reader: UrlReader | None = None,
                 on_sample: Callable[[bool, float, Activity | None], None] | None = None):
        self._probe = probe
        self._privacy = privacy
        self._coalescer = coalescer
        self._sink = sink
        self._interval = interval
        self._url_reader = url_reader
        self._on_sample = on_sample
        self._mode = TrackingMode.TRACKING
        self._mode_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def mode(self) -> TrackingMode:
        return self._mode

    def set_mode(self, mode: TrackingMode) -> None:
        with self._mode_lock:
            if mode is self._mode:
                return
            # Close the open activity so nothing spans a mode change (e.g. titles into privacy mode).
            self._emit(self._coalescer.close(time.time()))
            self._mode = mode
        log.info("tracking mode -> %s", mode.value)

    def set_url_reader(self, reader: UrlReader | None) -> None:
        self._url_reader = reader

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="collector", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        with self._mode_lock:
            self._emit(self._coalescer.close(time.time()))

    def tick(self) -> None:
        """One sampling step (exposed for tests)."""
        sample = self._probe.sample()
        current = None
        with self._mode_lock:
            if self._mode is not TrackingMode.PAUSED:
                url = ""
                if self._url_reader is not None and sample.app and not sample.session_locked:
                    url = self._url_reader.read(sample.hwnd, sample.app, sample.title)
                filtered = self._privacy.apply(sample.app, sample.title, url,
                                               privacy_mode=self._mode is TrackingMode.PRIVACY)
                self._emit(self._coalescer.feed(Observation(
                    ts=sample.ts, kind=filtered.kind, app=filtered.app, title=filtered.title,
                    url=filtered.url, idle_seconds=sample.idle_seconds,
                    session_locked=sample.session_locked)))
                current = self._coalescer.current
        if self._on_sample is not None:
            # Raw titles never leave the collector; listeners get state + the filtered activity.
            self._on_sample(sample.session_locked, sample.idle_seconds, current)

    def _run(self) -> None:
        log.info("collector started")
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - never let one bad sample kill tracking
                log.exception("collector tick failed")
            self._stop.wait(max(0.1, self._interval - (time.monotonic() - started)))
        log.info("collector stopped")

    def _emit(self, activities: list[Activity]) -> None:
        for activity in activities:
            try:
                self._sink(activity)
            except Exception:  # noqa: BLE001
                log.exception("failed to persist activity")
