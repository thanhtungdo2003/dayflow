from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QDate
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDateEdit, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ...models import Report
from .base import Page


class ReportPage(Page):
    title = "Báo cáo ngày"
    scrollable = False

    def build(self, layout: QVBoxLayout) -> None:
        bar = QHBoxLayout()
        self._date = QDateEdit(QDate.currentDate())
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("ddd, yyyy-MM-dd")
        self._date.dateChanged.connect(lambda _: self.refresh())
        self._generate = QPushButton("Tạo bản nháp")
        self._generate.clicked.connect(self._on_generate)
        self._save = QPushButton("Lưu")
        self._save.setObjectName("Primary")
        self._save.clicked.connect(self._on_save)
        copy_btn = QPushButton("Sao chép")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._editor.toPlainText()))
        export_btn = QPushButton("Xuất .md…")
        export_btn.clicked.connect(self._on_export)
        bar.addWidget(self._date)
        bar.addStretch(1)
        for b in (self._generate, self._save, copy_btn, export_btn):
            bar.addWidget(b)
        layout.addLayout(bar)
        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._editor = QPlainTextEdit()
        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._editor.setFont(mono)
        self._editor.textChanged.connect(self._on_edit)
        layout.addWidget(self._editor, 1)
        hint = QLabel("Mỗi dòng đều lấy từ hoạt động đã ghi hoặc danh sách công việc; dòng “(inferred)” là suy luận "
                      "— hãy xác nhận hoặc xoá. Có thể xoá các dòng Evidence trước khi gửi.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._report: Report | None = None
        self._dirty = False
        self._loading = False
        self._awaiting: str | None = None
        self.ctrl.report_ready.connect(self._on_ready)

    @property
    def day(self) -> str:
        return self._date.date().toString("yyyy-MM-dd")

    def show_day(self, day: str) -> None:
        self._date.setDate(QDate.fromString(day, "yyyy-MM-dd"))

    def refresh(self) -> None:
        if self._dirty and self._report is not None and self._report.day == self.day:
            return  # keep unsaved edits
        self._report = self.ctrl.reports.get(self.day)
        self._dirty = False
        self._show(self._report)

    def _show(self, report: Report | None) -> None:
        self._loading = True
        self._editor.setPlainText(report.markdown if report else "")
        self._loading = False
        if report is None:
            self._status.setText("Chưa có báo cáo cho ngày này. Hãy tạo bản nháp từ hoạt động đã ghi.")
        else:
            when = datetime.fromtimestamp(report.generated_at).strftime("%Y-%m-%d %H:%M")
            via = "quy tắc + AI viết lại" if report.generator == "rules+llm" else "quy tắc cục bộ"
            self._status.setText(f"Bản nháp tạo lúc {when} ({via})" + (" · đã chỉnh sửa" if report.edited else "")
                                 + (" · chưa lưu" if self._dirty else ""))

    def _on_edit(self) -> None:
        if not self._loading and not self._dirty:
            self._dirty = True
            self._show_status_suffix()

    def _show_status_suffix(self) -> None:
        if "chưa lưu" not in self._status.text():
            self._status.setText(self._status.text() + " · chưa lưu")

    def _on_generate(self) -> None:
        if self._dirty or (self._report and self._report.edited):
            answer = QMessageBox.question(self, "Thay báo cáo",
                                          "Thay nội dung hiện tại bằng bản nháp mới?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._generate.setEnabled(False)
        self._awaiting = self.day
        self._status.setText("Đang tạo…")
        self.ctrl.generate_report_async(self.day, save=False)

    def _on_ready(self, day: str, report: Report) -> None:
        requested = self._awaiting == day
        if requested:
            self._awaiting = None
            self._generate.setEnabled(True)
        if day != self.day:
            return
        if requested:
            self._report = report
            self._dirty = True  # a requested draft is not stored until the user saves it
            self._show(report)
        elif not self._dirty:
            self.refresh()      # scheduler draft (already saved) for the day on screen

    def _on_save(self) -> None:
        if self._report is None:
            if not self._editor.toPlainText().strip():
                return
            self._report = Report(day=self.day, generated_at=time.time(), sections={})
        text = self._editor.toPlainText()
        if text != self._report.markdown:
            self._report.edited = True
        self._report.markdown = text
        self.ctrl.reports.save(self._report)
        self._dirty = False
        self._show(self._report)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Xuất báo cáo", f"bao-cao-{self.day}.md",
                                              "Markdown (*.md);;Văn bản (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._editor.toPlainText())
            self._status.setText(f"Đã xuất ra {path} (bản này không được mã hoá).")
