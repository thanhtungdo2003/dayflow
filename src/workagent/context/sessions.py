"""Context engine: activities -> work sessions and day summaries. Pure functions."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..models import ACTIVE, PRIVATE, Activity


@dataclass
class WorkSession:
    start: float
    end: float
    activities: list[Activity] = field(default_factory=list)

    @property
    def active_seconds(self) -> float:
        return sum(a.duration for a in self.activities if a.is_work)

    @property
    def project(self) -> str:
        return _top(self.activities, lambda a: a.project)

    @property
    def top_app(self) -> str:
        return _top(self.activities, lambda a: a.app_name)

    @property
    def tickets(self) -> list[str]:
        seen: dict[str, float] = defaultdict(float)
        for a in self.activities:
            for t in a.tickets:
                seen[t] += a.duration
        return [t for t, _ in sorted(seen.items(), key=lambda kv: -kv[1])]

    @property
    def label(self) -> str:
        return self.project or (self.tickets[0] if self.tickets else "") or self.top_app or "Work"


def _top(activities: list[Activity], key) -> str:
    totals: Counter[str] = Counter()
    for a in activities:
        value = key(a)
        if value and a.kind == ACTIVE:
            totals[value] += a.duration
    return totals.most_common(1)[0][0] if totals else ""


def build_sessions(activities: list[Activity], break_seconds: float = 300) -> list[WorkSession]:
    """Group work activities into sessions; an away/locked span or gap > break_seconds splits."""
    sessions: list[WorkSession] = []
    current: WorkSession | None = None
    for act in sorted(activities, key=lambda a: a.start):
        if not act.is_work:
            if act.duration > break_seconds:
                current = None
            continue
        if current is None or act.start - current.end > break_seconds:
            current = WorkSession(start=act.start, end=act.end)
            sessions.append(current)
        current.activities.append(act)
        current.end = max(current.end, act.end)
    return sessions


@dataclass
class DaySummary:
    day: str
    active_seconds: float = 0.0
    private_seconds: float = 0.0
    away_seconds: float = 0.0
    first_ts: float | None = None
    last_ts: float | None = None
    by_category: dict[str, float] = field(default_factory=dict)
    by_app: dict[str, float] = field(default_factory=dict)
    by_project: dict[str, float] = field(default_factory=dict)
    by_ticket: dict[str, float] = field(default_factory=dict)
    sessions: list[WorkSession] = field(default_factory=list)

    @property
    def longest_session_seconds(self) -> float:
        return max((s.active_seconds for s in self.sessions), default=0.0)


def summarize_day(day: str, activities: list[Activity], break_seconds: float = 300) -> DaySummary:
    s = DaySummary(day=day)
    cat: Counter[str] = Counter()
    app: Counter[str] = Counter()
    proj: Counter[str] = Counter()
    tick: Counter[str] = Counter()
    for a in activities:
        if a.kind == ACTIVE:
            s.active_seconds += a.duration
            cat[a.category] += a.duration
            app[a.app_name or a.app] += a.duration
            if a.project:
                proj[a.project] += a.duration
            for t in a.tickets:
                tick[t] += a.duration
        elif a.kind == PRIVATE:
            s.private_seconds += a.duration
            cat["private"] += a.duration
        else:
            s.away_seconds += a.duration
        if a.is_work:
            s.first_ts = a.start if s.first_ts is None else min(s.first_ts, a.start)
            s.last_ts = a.end if s.last_ts is None else max(s.last_ts, a.end)
    s.by_category = dict(cat.most_common())
    s.by_app = dict(app.most_common())
    s.by_project = dict(proj.most_common())
    s.by_ticket = dict(tick.most_common())
    s.sessions = build_sessions(activities, break_seconds)
    return s


def format_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return f"{int(seconds)}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"
