from __future__ import annotations

from datetime import date, datetime

from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QHeaderView, QAbstractItemView,
)

from ...context.sessions import format_duration
from ...models import AWAY, LOCKED, PRIVATE
from ..widgets import CategoryBars, StatCard
from .base import Page


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    t.setShowGrid(False)
    t.setMinimumHeight(180)
    return t


def _fill(table: QTableWidget, rows: list[tuple[str, str]]) -> None:
    table.setRowCount(len(rows))
    for r, (name, value) in enumerate(rows):
        table.setItem(r, 0, QTableWidgetItem(name))
        table.setItem(r, 1, QTableWidgetItem(value))


class DashboardPage(Page):
    title = "Tổng quan"

    def build(self, layout: QVBoxLayout) -> None:
        self._now = QLabel("")
        self._now.setObjectName("Muted")
        self._now.setWordWrap(True)
        now_card = QFrame()
        now_card.setObjectName("Card")
        now_layout = QVBoxLayout(now_card)
        now_layout.setContentsMargins(16, 12, 16, 12)
        heading = QLabel("Hiện tại")
        heading.setObjectName("CardLabel")
        now_layout.addWidget(heading)
        now_layout.addWidget(self._now)
        layout.addWidget(now_card)

        cards = QGridLayout()
        cards.setSpacing(12)
        self._active = StatCard("Hoạt động hôm nay")
        self._sessions = StatCard("Phiên làm việc")
        self._focus = StatCard("Phiên dài nhất")
        self._project = StatCard("Dự án chính")
        for i, card in enumerate((self._active, self._sessions, self._focus, self._project)):
            cards.addWidget(card, 0, i)
        layout.addLayout(cards)

        bars_card = QFrame()
        bars_card.setObjectName("Card")
        bars_layout = QVBoxLayout(bars_card)
        bars_layout.setContentsMargins(16, 12, 16, 12)
        label = QLabel("Thời gian theo nhóm")
        label.setObjectName("CardLabel")
        bars_layout.addWidget(label)
        self._bars = CategoryBars()
        bars_layout.addWidget(self._bars)
        layout.addWidget(bars_card)

        tables = QHBoxLayout()
        self._projects = _table(["Dự án", "Thời gian"])
        self._apps = _table(["Ứng dụng", "Thời gian"])
        tables.addWidget(self._projects)
        tables.addWidget(self._apps)
        layout.addLayout(tables)
        layout.addStretch(1)

    def refresh(self) -> None:
        self.update_now(self.ctrl.current_activity)
        s = self.ctrl.day_summary(date.today().isoformat())
        self._active.set_value(format_duration(s.active_seconds) if s.active_seconds else "0m",
                               f"Hoạt động riêng tư: {format_duration(s.private_seconds)}")
        self._sessions.set_value(str(len(s.sessions)))
        self._focus.set_value(format_duration(s.longest_session_seconds) if s.sessions else "—")
        top = next(iter(s.by_project), "—")
        self._project.set_value(top if len(top) <= 18 else top[:17] + "…", top)
        self._bars.set_data(s.by_category)
        _fill(self._projects, [(p, format_duration(t)) for p, t in list(s.by_project.items())[:10]])
        _fill(self._apps, [(a, format_duration(t)) for a, t in list(s.by_app.items())[:10]])

    def update_now(self, act) -> None:
        error = self.ctrl.tracking_error
        if error:
            self._now.setText(error)
        elif act is None:
            self._now.setText("Hiện không theo dõi.")
        elif act.kind == AWAY:
            self._now.setText(f"Vắng mặt từ {datetime.fromtimestamp(act.start):%H:%M}.")
        elif act.kind == LOCKED:
            self._now.setText("Màn hình đang khoá.")
        elif act.kind == PRIVATE:
            self._now.setText(f"Hoạt động riêng tư từ {datetime.fromtimestamp(act.start):%H:%M} (không ghi chi tiết).")
        else:
            parts = [act.app_name or act.app]
            if act.project:
                parts.append(f"dự án {act.project}")
            if act.tickets:
                parts.append(", ".join(act.tickets))
            text = " · ".join(parts) + f" — từ {datetime.fromtimestamp(act.start):%H:%M}"
            if act.title:
                text += f"\n{act.title}"
            self._now.setText(text)
