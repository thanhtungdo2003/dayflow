"""Typed access to vault collections. The only code that knows collection names."""

from __future__ import annotations

from datetime import date, timedelta

from ..models import Activity, Report, Task
from .vault import Vault

ACTIVITIES = "activities"
REPORTS = "reports"
TASKS = "tasks"
SECRETS = "secrets"


class ActivityRepository:
    def __init__(self, vault: Vault):
        self._vault = vault

    def upsert(self, activity: Activity) -> None:
        self._vault.put(ACTIVITIES, activity.id, activity.to_dict(), day=activity.day)

    def list_day(self, day: str) -> list[Activity]:
        items = [Activity.from_dict(d) for d in self._vault.list(ACTIVITIES, day=day)]
        return sorted(items, key=lambda a: a.start)

    def list_range(self, end_day: date, days: int) -> list[Activity]:
        out: list[Activity] = []
        for offset in range(days - 1, -1, -1):
            out.extend(self.list_day((end_day - timedelta(days=offset)).isoformat()))
        return out

    def delete_day(self, day: str) -> int:
        return self._vault.delete_day(ACTIVITIES, day)


class ReportRepository:
    def __init__(self, vault: Vault):
        self._vault = vault

    def get(self, day: str) -> Report | None:
        data = self._vault.get(REPORTS, day)
        return Report.from_dict(data) if data else None

    def save(self, report: Report) -> None:
        self._vault.put(REPORTS, report.day, report.to_dict(), day=report.day)

    def delete(self, day: str) -> None:
        self._vault.delete(REPORTS, day)


class TaskRepository:
    def __init__(self, vault: Vault):
        self._vault = vault

    def list(self) -> list[Task]:
        tasks = [Task.from_dict(d) for d in self._vault.list(TASKS)]
        return sorted(tasks, key=lambda t: (t.status == "done", -t.updated_at))

    def save(self, task: Task) -> None:
        self._vault.put(TASKS, task.id, task.to_dict())

    def delete(self, task_id: str) -> None:
        self._vault.delete(TASKS, task_id)


class SecretRepository:
    """API keys and similar: stored encrypted in the vault, never in config.json."""

    def __init__(self, vault: Vault):
        self._vault = vault

    def get(self, name: str) -> str:
        data = self._vault.get(SECRETS, name) if self._vault.is_unlocked else None
        return data.get("value", "") if data else ""

    def set(self, name: str, value: str) -> None:
        if value:
            self._vault.put(SECRETS, name, {"value": value})
        else:
            self._vault.delete(SECRETS, name)
