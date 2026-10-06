"""Coalesce periodic window observations into activities.

Pure state machine (no I/O, no clock): feed observations in time order, receive the activities
that must be persisted. An open activity is emitted when it closes and every `flush_seconds`
while it stays open, so the store is at most one flush interval behind.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..context.extractor import ContextExtractor
from ..models import ACTIVE, AWAY, LOCKED, Activity, new_id


@dataclass
class Observation:
    ts: float
    kind: str               # ACTIVE | PRIVATE (from the privacy filter)
    app: str = ""
    title: str = ""
    url: str = ""
    idle_seconds: float = 0.0
    session_locked: bool = False


def _next_midnight(ts: float) -> float:
    dt = datetime.fromtimestamp(ts)
    return (datetime(dt.year, dt.month, dt.day) + timedelta(days=1)).timestamp()


class Coalescer:
    def __init__(self, extractor: ContextExtractor, idle_seconds: float = 180,
                 min_activity_seconds: float = 3, flush_seconds: float = 30,
                 max_gap_seconds: float = 30):
        self._extractor = extractor
        self._idle = idle_seconds
        self._min = min_activity_seconds
        self._flush = flush_seconds
        self._max_gap = max_gap_seconds
        self._current: Activity | None = None
        self._key: tuple | None = None
        self._last_ts: float | None = None
        self._last_flush: float = 0.0
        self._flushed = False

    @property
    def current(self) -> Activity | None:
        """A copy of the open activity (safe to hand to another thread)."""
        return self._copy(self._current) if self._current else None

    def set_extractor(self, extractor: ContextExtractor) -> None:
        self._extractor = extractor  # applies to activities opened from now on

    def feed(self, obs: Observation) -> list[Activity]:
        out: list[Activity] = []
        floor: float | None = None  # a new activity may not start before the previous one ended
        # A long gap means the machine slept or the collector stalled: we know nothing about it.
        if self._last_ts is not None and obs.ts - self._last_ts > self._max_gap:
            out += self._close(self._last_ts)
            floor = self._last_ts
        self._last_ts = obs.ts

        kind, start = self._classify(obs)
        key = (kind, obs.app, obs.title, obs.url) if kind not in (AWAY, LOCKED) else (kind,)

        if self._current is not None:
            midnight = _next_midnight(self._current.start)
            if midnight <= obs.ts:
                out += self._close(midnight)
                floor = midnight

        if self._current is None or key != self._key:
            if self._current is not None:
                floor = max(start, self._current.start)
                out += self._close(floor)
            self._open(obs, kind, key, start if floor is None else max(start, floor))
        self._current.end = obs.ts

        if obs.ts - self._last_flush >= self._flush and self._current.duration >= self._min:
            out.append(self._snapshot())
            self._last_flush = obs.ts
            self._flushed = True
        return out

    def close(self, ts: float | None = None) -> list[Activity]:
        """Close the open activity (pause, shutdown). Returns it if worth keeping."""
        out = self._close(ts if ts is not None else (self._last_ts or 0.0))
        self._last_ts = None
        return out

    def _classify(self, obs: Observation) -> tuple[str, float]:
        if obs.session_locked:
            return LOCKED, obs.ts
        if obs.idle_seconds >= self._idle:
            # Backdate: the user left when input stopped, not when we noticed.
            return AWAY, obs.ts - obs.idle_seconds
        return obs.kind, obs.ts

    def _open(self, obs: Observation, kind: str, key: tuple, start: float) -> None:
        start = min(start, obs.ts)
        if kind in (AWAY, LOCKED):
            act = Activity(id=new_id(), start=start, end=obs.ts, kind=kind)
        else:
            ctx = self._extractor.extract(obs.app, obs.title, obs.url)
            act = Activity(id=new_id(), start=start, end=obs.ts, kind=kind, app=obs.app,
                           app_name=ctx.app_name, title=ctx.title, url=obs.url, domain=ctx.domain,
                           category=ctx.category if kind == ACTIVE else "private",
                           project=ctx.project, file=ctx.file, tickets=ctx.tickets)
        self._current, self._key = act, key
        self._last_flush, self._flushed = obs.ts, False

    def _close(self, end: float) -> list[Activity]:
        act = self._current
        self._current, self._key = None, None
        if act is None:
            return []
        act.end = max(act.start, end)
        if act.duration < self._min and not self._flushed:
            return []
        return [self._copy(act)]

    def _snapshot(self) -> Activity:
        return self._copy(self._current)

    @staticmethod
    def _copy(act: Activity) -> Activity:
        return Activity.from_dict(act.to_dict())
