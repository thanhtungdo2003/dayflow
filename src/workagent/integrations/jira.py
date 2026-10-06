"""Jira helpers (MVP: local only — ticket detection and browse links; no API calls).

A future Jira sync would live here, consume ActivityRepository/TaskRepository and keep its API
token in SecretRepository. It must remain opt-in like every other network feature.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import ACTIVE, Activity


def browse_url(base_url: str, ticket: str) -> str:
    if not base_url or not ticket:
        return ""
    return f"{base_url.rstrip('/')}/browse/{ticket}"


def time_by_ticket(activities: list[Activity]) -> dict[str, float]:
    """Seconds of active work attributed to each ticket key."""
    totals: dict[str, float] = defaultdict(float)
    for a in activities:
        if a.kind == ACTIVE:
            for ticket in a.tickets:
                totals[ticket] += a.duration
    return dict(totals)
