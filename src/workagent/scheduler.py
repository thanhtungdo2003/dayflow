"""Scheduler decisions as a pure function of time and state; the controller executes them.

* Daily report drafts: today's after `report.time`, and yesterday's as a catch-up (the app may
  have been off or locked at report time). Each day is attempted once per run and never when a
  report already exists, so user edits are not overwritten. Requires the vault to be unlocked.
* Auto-lock after N minutes of system idle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable


@dataclass
class Actions:
    generate_reports: list[str] = field(default_factory=list)
    lock_vault: bool = False


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except ValueError:
        pass
    return 17, 30


class Scheduler:
    def __init__(self, report_time: str = "17:30", auto_report: bool = True,
                 auto_lock_idle_minutes: int = 15):
        self.report_time = report_time
        self.auto_report = auto_report
        self.auto_lock_idle_minutes = auto_lock_idle_minutes
        self._attempted: set[str] = set()

    def tick(self, now: datetime, idle_seconds: float, unlocked: bool,
             has_report: Callable[[str], bool] = lambda day: False) -> Actions:
        actions = Actions()
        if not unlocked:
            return actions
        if self.auto_report:
            h, m = parse_hhmm(self.report_time)
            due = [(now.date() - timedelta(days=1)).isoformat()]
            if now >= now.replace(hour=h, minute=m, second=0, microsecond=0):
                due.append(now.date().isoformat())
            for day in due:
                if day in self._attempted:
                    continue
                self._attempted.add(day)
                if not has_report(day):
                    actions.generate_reports.append(day)
        if self.auto_lock_idle_minutes > 0 and idle_seconds >= self.auto_lock_idle_minutes * 60:
            actions.lock_vault = True
        return actions
