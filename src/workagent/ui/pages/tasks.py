from __future__ import annotations

import time
import webbrowser
from datetime import date

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ...context.sessions import format_duration
from ...integrations.jira import browse_url, time_by_ticket
from ...models import TASK_STATUSES, Task, new_id
from .base import Page

STATUS_LABELS = {"todo": "Cần làm", "doing": "Đang làm", "blocked": "Bị chặn", "done": "Hoàn thành"}


class TasksPage(Page):
    title = "Công việc"

    def build(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Trạng thái", "Công việc", "Ticket", "Dự án", "Đã ghi (7 ngày)"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._load_selected)
        self._table.setMinimumHeight(320)
        row.addWidget(self._table, 3)

        form_box = QGroupBox("Chi tiết công việc")
        form = QFormLayout(form_box)
        self._title = QLineEdit()
        self._status = QComboBox()
        for status in TASK_STATUSES:
            self._status.addItem(STATUS_LABELS[status], status)
        self._ticket = QLineEdit()
        self._ticket.setPlaceholderText("vd: PROJ-123")
        self._project = QLineEdit()
        self._notes = QPlainTextEdit()
        self._notes.setFixedHeight(90)
        self._support = QCheckBox("Cần hỗ trợ / escalate")
        form.addRow("Tiêu đề", self._title)
        form.addRow("Trạng thái", self._status)
        form.addRow("Ticket", self._ticket)
        form.addRow("Dự án", self._project)
        form.addRow("Ghi chú", self._notes)
        form.addRow("", self._support)
        buttons = QHBoxLayout()
        new_btn, save_btn, del_btn = QPushButton("Mới"), QPushButton("Lưu"), QPushButton("Xoá")
        save_btn.setObjectName("Primary")
        del_btn.setObjectName("Danger")
        self._open_btn = QPushButton("Mở trên Jira")
        new_btn.clicked.connect(self._new)
        save_btn.clicked.connect(self._save)
        del_btn.clicked.connect(self._delete)
        self._open_btn.clicked.connect(self._open_ticket)
        for b in (new_btn, save_btn, del_btn, self._open_btn):
            buttons.addWidget(b)
        form.addRow(buttons)
        row.addWidget(form_box, 2)
        layout.addLayout(row)

        detected = QGroupBox("Ticket phát hiện từ hoạt động (7 ngày qua)")
        dl = QVBoxLayout(detected)
        self._detected = QListWidget()
        self._detected.setFixedHeight(140)
        self._detected.itemDoubleClicked.connect(self._add_from_detected)
        dl.addWidget(self._detected)
        add_btn = QPushButton("Tạo công việc từ ticket đã chọn")
        add_btn.clicked.connect(lambda: self._add_from_detected(self._detected.currentItem()))
        dl.addWidget(add_btn)
        layout.addWidget(detected)
        layout.addStretch(1)
        self._tasks: list[Task] = []
        self._editing: Task | None = None

    def refresh(self) -> None:
        self._tasks = self.ctrl.tasks.list()
        tracked = time_by_ticket(self.ctrl.activities.list_range(date.today(), 7))
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._tasks))
        for r, t in enumerate(self._tasks):
            values = [STATUS_LABELS.get(t.status, t.status) + (" ⚑" if t.needs_support else ""), t.title,
                      t.ticket, t.project, format_duration(tracked[t.ticket]) if t.ticket in tracked else ""]
            for c, v in enumerate(values):
                self._table.setItem(r, c, QTableWidgetItem(v))
        self._table.blockSignals(False)
        known = {t.ticket for t in self._tasks}
        self._detected.clear()
        for ticket, secs in sorted(tracked.items(), key=lambda kv: -kv[1]):
            item = QListWidgetItem(f"{ticket} — {format_duration(secs)}"
                                   + ("  (đã có công việc)" if ticket in known else ""))
            item.setData(256, ticket)
            self._detected.addItem(item)
        self._open_btn.setEnabled(bool(self.ctrl.config.integrations.jira_base_url))

    def _set_status(self, status: str) -> None:
        self._status.setCurrentIndex(max(0, self._status.findData(status)))

    def _load_selected(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        t = self._tasks[rows[0].row()]
        self._editing = t
        self._title.setText(t.title)
        self._set_status(t.status)
        self._ticket.setText(t.ticket)
        self._project.setText(t.project)
        self._notes.setPlainText(t.notes)
        self._support.setChecked(t.needs_support)

    def _new(self) -> None:
        self._editing = None
        self._table.clearSelection()
        for w in (self._title, self._ticket, self._project):
            w.clear()
        self._notes.clear()
        self._set_status("todo")
        self._support.setChecked(False)
        self._title.setFocus()

    def _save(self) -> None:
        title = self._title.text().strip()
        if not title:
            self._title.setFocus()
            return
        t = self._editing or Task(id=new_id(), title=title)
        status = self._status.currentData()
        if status == "done" and t.status != "done":
            t.done_at = time.time()
        elif status != "done":
            t.done_at = None
        t.title, t.status = title, status
        t.ticket = self._ticket.text().strip().upper()
        t.project = self._project.text().strip()
        t.notes = self._notes.toPlainText().strip()
        t.needs_support = self._support.isChecked()
        t.updated_at = time.time()
        self.ctrl.tasks.save(t)
        self._editing = t
        self.refresh()

    def _delete(self) -> None:
        if self._editing is not None:
            self.ctrl.tasks.delete(self._editing.id)
            self._new()
            self.refresh()

    def _add_from_detected(self, item) -> None:
        if item is None:
            return
        self._new()
        ticket = item.data(256)
        self._ticket.setText(ticket)
        self._title.setText(ticket)
        self._set_status("doing")
        self._title.setFocus()
        self._title.selectAll()

    def _open_ticket(self) -> None:
        url = browse_url(self.ctrl.config.integrations.jira_base_url, self._ticket.text().strip())
        if url:
            webbrowser.open(url)
