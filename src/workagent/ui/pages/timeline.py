from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDateEdit, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ...context.sessions import build_sessions, format_duration
from ...models import AWAY, LOCKED, PRIVATE, Activity
from .. import theme
from ..widgets import TimelineStrip
from .base import Page


def _hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _legend() -> QWidget:
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(8, 0, 8, 0)
    row.setSpacing(14)
    for key, label in theme.CATEGORY_LABELS.items():
        swatch = QLabel()
        swatch.setFixedSize(10, 10)
        swatch.setStyleSheet(f"background: {theme.CATEGORY_COLORS[key]}; border-radius: 2px;")
        text = QLabel(label)
        text.setObjectName("Hint")
        pair = QHBoxLayout()
        pair.setSpacing(5)
        pair.addWidget(swatch)
        pair.addWidget(text)
        row.addLayout(pair)
    row.addStretch(1)
    return w


class TimelinePage(Page):
    title = "Dòng thời gian"
    scrollable = False

    def build(self, layout: QVBoxLayout) -> None:
        bar = QHBoxLayout()
        prev_btn, next_btn, today_btn = QPushButton("◀"), QPushButton("▶"), QPushButton("Hôm nay")
        self._date = QDateEdit(QDate.currentDate())
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("ddd, yyyy-MM-dd")
        self._date.dateChanged.connect(lambda _: self.refresh())
        prev_btn.clicked.connect(lambda: self._date.setDate(self._date.date().addDays(-1)))
        next_btn.clicked.connect(lambda: self._date.setDate(self._date.date().addDays(1)))
        today_btn.clicked.connect(lambda: self._date.setDate(QDate.currentDate()))
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Lọc theo ứng dụng, tiêu đề, dự án, ticket…")
        self._filter.textChanged.connect(lambda _: self._populate())
        delete_btn = QPushButton("Xoá dữ liệu ngày này…")
        delete_btn.setObjectName("Danger")
        delete_btn.clicked.connect(self._delete_day)
        for w in (prev_btn, self._date, next_btn, today_btn):
            bar.addWidget(w)
        bar.addWidget(self._filter, 1)
        bar.addWidget(delete_btn)
        layout.addLayout(bar)

        strip_card = QFrame()
        strip_card.setObjectName("Card")
        strip_layout = QVBoxLayout(strip_card)
        strip_layout.setContentsMargins(8, 8, 8, 8)
        self._summary = QLabel("")
        self._summary.setObjectName("Muted")
        strip_layout.addWidget(self._summary)
        self._strip = TimelineStrip()
        strip_layout.addWidget(self._strip)
        strip_layout.addWidget(_legend())
        layout.addWidget(strip_card)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(6)
        self._tree.setHeaderLabels(["Thời gian", "Thời lượng", "Ứng dụng", "Chi tiết", "Dự án", "Ticket"])
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        header = self._tree.header()
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 150), (1, 80), (2, 130), (4, 120), (5, 110)):
            self._tree.setColumnWidth(col, width)
        layout.addWidget(self._tree, 1)
        self._acts: list[Activity] = []

    @property
    def day(self) -> str:
        return self._date.date().toString("yyyy-MM-dd")

    def refresh(self) -> None:
        self._acts = self.ctrl.day_activities(self.day)
        start = datetime.strptime(self.day, "%Y-%m-%d").timestamp()
        self._strip.set_activities(self._acts, start)
        s = self.ctrl.day_summary(self.day)
        if s.first_ts is None:
            self._summary.setText("Không có hoạt động nào trong ngày này.")
        else:
            self._summary.setText(f"{format_duration(s.active_seconds)} hoạt động · {_hm(s.first_ts)}–{_hm(s.last_ts)} · "
                                  f"{len(s.sessions)} phiên · vắng mặt {format_duration(s.away_seconds)}")
        self._populate()

    def _populate(self) -> None:
        needle = self._filter.text().strip().lower()
        self._tree.clear()
        acts = self._acts
        if needle:
            acts = [a for a in acts if needle in
                    f"{a.app_name} {a.title} {a.project} {a.file} {' '.join(a.tickets)} {a.domain}".lower()]
        for session in build_sessions(acts):
            top = QTreeWidgetItem([f"{_hm(session.start)}–{_hm(session.end)}",
                                   format_duration(session.active_seconds), session.top_app,
                                   f"Phiên: {session.label}", session.project, ", ".join(session.tickets[:3])])
            font = top.font(0)
            font.setBold(True)
            for col in range(6):
                top.setFont(col, font)
            self._tree.addTopLevelItem(top)
            for a in session.activities:
                details = a.title or ("(riêng tư — không ghi chi tiết)" if a.kind == PRIVATE else "")
                item = QTreeWidgetItem([f"{_hm(a.start)}–{_hm(a.end)}", format_duration(a.duration),
                                        a.app_name or a.app, details, a.project, ", ".join(a.tickets)])
                item.setToolTip(3, "\n".join(x for x in (a.title, a.url, a.file) if x))
                color = theme.CATEGORY_COLORS["private" if a.kind == PRIVATE else theme.category_key(
                    "other" if a.category == "system" else a.category)]
                item.setForeground(2, QColor(theme.TEXT))
                item.setData(0, Qt.ItemDataRole.DecorationRole, QColor(color))
                top.addChild(item)
        breaks = [a for a in acts if a.kind in (AWAY, LOCKED) and a.duration >= 300]
        if breaks and not needle:
            item = QTreeWidgetItem(["", format_duration(sum(a.duration for a in breaks)), "",
                                    f"Nghỉ / vắng mặt: {len(breaks)} lần", "", ""])
            item.setForeground(3, QColor(theme.TEXT_2))
            self._tree.addTopLevelItem(item)
        if self._tree.topLevelItemCount() <= 3:
            self._tree.expandAll()

    def _delete_day(self) -> None:
        answer = QMessageBox.warning(
            self, "Xoá dữ liệu ngày", f"Xoá vĩnh viễn toàn bộ hoạt động đã ghi ngày {self.day}?\n"
            "Báo cáo của ngày đó vẫn được giữ lại.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.ctrl.activities.delete_day(self.day)
            self.refresh()
