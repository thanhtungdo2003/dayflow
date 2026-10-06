"""Domain models shared across modules. Plain dataclasses, JSON-serialisable via to_dict/from_dict."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any


def new_id() -> str:
    return uuid.uuid4().hex


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _from_dict(cls, data: dict[str, Any]):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


# Activity kinds
ACTIVE = "active"      # user working in an app/window
AWAY = "away"          # idle beyond threshold
LOCKED = "locked"      # Windows session locked
PRIVATE = "private"    # sensitive app/window: time only, no details


@dataclass
class Activity:
    id: str
    start: float
    end: float
    kind: str = ACTIVE
    app: str = ""            # executable name, lower-case
    app_name: str = ""       # friendly name
    title: str = ""          # redacted window title
    url: str = ""            # sanitised URL (only if URL capture enabled)
    domain: str = ""
    category: str = "other"
    project: str = ""
    file: str = ""
    tickets: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def day(self) -> str:
        return day_of(self.start)

    @property
    def is_work(self) -> bool:
        return self.kind in (ACTIVE, PRIVATE)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Activity":
        return _from_dict(cls, data)


TASK_STATUSES = ("todo", "doing", "blocked", "done")


@dataclass
class Task:
    id: str
    title: str
    status: str = "todo"
    ticket: str = ""
    project: str = ""
    notes: str = ""
    needs_support: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    done_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return _from_dict(cls, data)


@dataclass
class Evidence:
    start: float
    end: float
    label: str               # e.g. "VS Code — vault.py"
    activity_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        return _from_dict(cls, data)


@dataclass
class ReportItem:
    text: str
    evidence: list[Evidence] = field(default_factory=list)
    inferred: bool = False   # heuristic conclusion the user should confirm

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportItem":
        item = _from_dict(cls, data)
        item.evidence = [Evidence.from_dict(e) for e in data.get("evidence", [])]
        return item


REPORT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("progress", "Progress Today"),
    ("issues", "Issues Found"),
    ("blocks", "Block"),
    ("support", "Need Support / Escalation"),
    ("plan", "Plan Tomorrow"),
)


@dataclass
class Report:
    day: str
    generated_at: float
    sections: dict[str, list[ReportItem]]
    markdown: str = ""          # user-editable text; source of truth once edited
    edited: bool = False
    generator: str = "rules"
    ai_error: str = ""          # why an AI step was skipped (shown to the user)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Report":
        report = _from_dict(cls, data)
        report.sections = {k: [ReportItem.from_dict(i) for i in v]
                           for k, v in data.get("sections", {}).items()}
        return report
