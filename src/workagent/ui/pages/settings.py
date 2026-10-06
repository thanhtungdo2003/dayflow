from __future__ import annotations

import copy
import os

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTimeEdit, QVBoxLayout,
)

from ...config import Config
from ...paths import data_dir
from ...storage.vault import MIN_PIN_LENGTH, VaultError, WrongPinError
from .ai_settings import AiSettingsBox
from .base import Page


def _lines(widget: QPlainTextEdit) -> list[str]:
    return [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]


def _text_list(values: list[str], height: int = 90) -> QPlainTextEdit:
    w = QPlainTextEdit("\n".join(values))
    w.setFixedHeight(height)
    return w


class ChangePinDialog(QDialog):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Đổi PIN")
        self._ctrl = ctrl
        form = QFormLayout(self)
        self._old, self._new, self._confirm = QLineEdit(), QLineEdit(), QLineEdit()
        for w in (self._old, self._new, self._confirm):
            w.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("PIN hiện tại", self._old)
        form.addRow("PIN mới", self._new)
        form.addRow("Nhập lại PIN mới", self._confirm)
        self._error = QLabel("")
        self._error.setObjectName("Error")
        form.addRow(self._error)
        note = QLabel("Chỉ lớp bọc khoá được mã hoá lại; dữ liệu của bạn giữ nguyên.")
        note.setObjectName("Hint")
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self) -> None:
        if len(self._new.text()) < MIN_PIN_LENGTH:
            self._error.setText(f"Cần ít nhất {MIN_PIN_LENGTH} ký tự.")
        elif self._new.text() != self._confirm.text():
            self._error.setText("Hai lần nhập PIN mới không khớp.")
        else:
            try:
                self._ctrl.change_pin(self._old.text(), self._new.text())
                self.accept()
            except WrongPinError:
                self._error.setText("PIN hiện tại không đúng.")
            except VaultError as exc:
                self._error.setText(str(exc))


class SettingsPage(Page):
    title = "Cài đặt"

    def build(self, layout: QVBoxLayout) -> None:
        save = QPushButton("Lưu cài đặt")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        self.header_actions.addWidget(save)

        general = QGroupBox("Chung")
        g = QFormLayout(general)
        self._startup = QCheckBox("Khởi động cùng Windows (đăng ký file .exe đã cài)")
        self._minimized = QCheckBox("Khởi động thu nhỏ xuống khay hệ thống")
        self._debug = QCheckBox("Ghi log debug (không bao giờ ghi tiêu đề, URL hay nội dung báo cáo)")
        self._ui_mode = QComboBox()
        self._ui_mode.addItem("Ứng dụng (cửa sổ này)", "desktop")
        self._ui_mode.addItem("Web (mở trong trình duyệt, giao diện tối)", "web")
        self._web_port = QSpinBox()
        self._web_port.setRange(1024, 65535)
        g.addRow("Kiểu giao diện", self._ui_mode)
        g.addRow("Cổng web (127.0.0.1)", self._web_port)
        for w in (self._startup, self._minimized, self._debug):
            g.addRow(w)
        layout.addWidget(general)

        tracking = QGroupBox("Theo dõi")
        t = QFormLayout(tracking)
        self._sample = QSpinBox()
        self._sample.setRange(1, 30)
        self._sample.setSuffix(" giây")
        self._idle = QSpinBox()
        self._idle.setRange(30, 3600)
        self._idle.setSuffix(" giây")
        self._paused_start = QCheckBox("Khởi động ở trạng thái tạm dừng")
        t.addRow("Lấy mẫu mỗi", self._sample)
        t.addRow("Coi là vắng mặt sau khi không thao tác", self._idle)
        t.addRow(self._paused_start)
        hint = QLabel("Thay đổi chu kỳ lấy mẫu có hiệu lực sau khi khởi động lại.")
        hint.setObjectName("Hint")
        t.addRow(hint)
        layout.addWidget(tracking)

        privacy = QGroupBox("Quyền riêng tư")
        p = QFormLayout(privacy)
        self._url_mode = QComboBox()
        self._url_mode.addItem("Tắt — chỉ ghi tiêu đề cửa sổ", "off")
        self._url_mode.addItem("Chỉ tên miền", "domain")
        self._url_mode.addItem("URL đầy đủ, bỏ query/fragment", "full")
        self._redact = QCheckBox("Che các chuỗi trông giống bí mật trong tiêu đề")
        self._apps = _text_list([])
        self._keywords = _text_list([])
        self._domains = _text_list([])
        p.addRow("URL trình duyệt", self._url_mode)
        p.addRow(self._redact)
        p.addRow("Ứng dụng bị chặn (.exe)", self._apps)
        p.addRow("Từ khoá tiêu đề bị chặn", self._keywords)
        p.addRow("Tên miền bị chặn", self._domains)
        note = QLabel("Mục bị chặn chỉ được ghi là thời gian “Riêng tư”, không có tiêu đề hay URL. Ghi URL "
                      "cần cài thêm gói tuỳ chọn 'uiautomation'.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        p.addRow(note)
        layout.addWidget(privacy)

        security = QGroupBox("Bảo mật")
        s = QFormLayout(security)
        self._lock_on_win = QCheckBox("Khoá kho dữ liệu khi Windows bị khoá")
        self._auto_lock = QSpinBox()
        self._auto_lock.setRange(0, 480)
        self._auto_lock.setSuffix(" phút không thao tác (0 = không bao giờ)")
        pin_btn = QPushButton("Đổi PIN…")
        pin_btn.clicked.connect(lambda: ChangePinDialog(self.ctrl, self).exec())
        lock_btn = QPushButton("Khoá ngay")
        lock_btn.clicked.connect(self.ctrl.lock)
        s.addRow(self._lock_on_win)
        s.addRow("Tự khoá sau", self._auto_lock)
        row = QHBoxLayout()
        row.addWidget(pin_btn)
        row.addWidget(lock_btn)
        row.addStretch(1)
        s.addRow(row)
        layout.addWidget(security)

        report = QGroupBox("Báo cáo ngày")
        r = QFormLayout(report)
        self._auto_report = QCheckBox("Tự động tạo bản nháp báo cáo")
        self._report_time = QTimeEdit()
        self._report_time.setDisplayFormat("HH:mm")
        self._block_minutes = QSpinBox()
        self._block_minutes.setRange(10, 480)
        self._block_minutes.setSuffix(" phút cho một vấn đề")
        r.addRow(self._auto_report)
        r.addRow("Tạo lúc", self._report_time)
        r.addRow("Đánh dấu có thể bị block sau", self._block_minutes)
        layout.addWidget(report)

        self._ai_box = AiSettingsBox(self.ctrl)
        layout.addWidget(self._ai_box)

        integ = QGroupBox("Tích hợp")
        i = QFormLayout(integ)
        self._jira = QLineEdit()
        self._jira.setPlaceholderText("https://yourcompany.atlassian.net")
        self._ticket_projects = QLineEdit()
        self._ticket_projects.setPlaceholderText("PROJ, OPS  (để trống = nhận mọi dạng KEY-123)")
        self._rules = _text_list([])
        self._rules.setPlaceholderText("mỗi dòng một quy tắc:  chữ trong tiêu đề => Tên dự án")
        i.addRow("Jira base URL", self._jira)
        i.addRow("Mã dự án của ticket", self._ticket_projects)
        i.addRow("Quy tắc dự án", self._rules)
        layout.addWidget(integ)

        data = QGroupBox("Dữ liệu")
        d = QHBoxLayout(data)
        open_btn = QPushButton("Mở thư mục dữ liệu")
        open_btn.clicked.connect(lambda: os.startfile(str(data_dir())))  # noqa: S606 - local folder
        d.addWidget(QLabel(str(data_dir())))
        d.addStretch(1)
        d.addWidget(open_btn)
        layout.addWidget(data)
        layout.addStretch(1)

    def refresh(self) -> None:
        c = self.ctrl.config
        self._startup.setChecked(c.run_at_startup)
        self._ui_mode.setCurrentIndex(max(0, self._ui_mode.findData(c.ui_mode)))
        self._web_port.setValue(c.web_port)
        self._minimized.setChecked(c.start_minimized)
        self._debug.setChecked(c.debug)
        self._sample.setValue(int(c.tracking.sample_seconds))
        self._idle.setValue(c.tracking.idle_seconds)
        self._paused_start.setChecked(c.tracking.start_paused)
        self._url_mode.setCurrentIndex(max(0, self._url_mode.findData(c.privacy.browser_url_mode)))
        self._redact.setChecked(c.privacy.redact_secrets)
        self._apps.setPlainText("\n".join(c.privacy.blocked_apps))
        self._keywords.setPlainText("\n".join(c.privacy.blocked_keywords))
        self._domains.setPlainText("\n".join(c.privacy.blocked_domains))
        self._lock_on_win.setChecked(c.security.lock_on_windows_lock)
        self._auto_lock.setValue(c.security.auto_lock_idle_minutes)
        self._auto_report.setChecked(c.report.auto_generate)
        self._report_time.setTime(QTime.fromString(c.report.time, "HH:mm"))
        self._block_minutes.setValue(c.report.block_minutes)
        self._ai_box.load(c.ai)
        self._jira.setText(c.integrations.jira_base_url)
        self._ticket_projects.setText(", ".join(c.integrations.ticket_projects))
        self._rules.setPlainText("\n".join(f"{r['match']} => {r['project']}" for r in c.integrations.project_rules
                                           if r.get("match") and r.get("project")))

    def _save(self) -> None:
        c: Config = copy.deepcopy(self.ctrl.config)
        c.run_at_startup = self._startup.isChecked()
        c.ui_mode = self._ui_mode.currentData()
        c.web_port = self._web_port.value()
        c.start_minimized = self._minimized.isChecked()
        c.debug = self._debug.isChecked()
        c.tracking.sample_seconds = float(self._sample.value())
        c.tracking.idle_seconds = self._idle.value()
        c.tracking.start_paused = self._paused_start.isChecked()
        c.privacy.browser_url_mode = self._url_mode.currentData()
        c.privacy.redact_secrets = self._redact.isChecked()
        c.privacy.blocked_apps = [x.lower() for x in _lines(self._apps)]
        c.privacy.blocked_keywords = _lines(self._keywords)
        c.privacy.blocked_domains = [x.lower() for x in _lines(self._domains)]
        c.security.lock_on_windows_lock = self._lock_on_win.isChecked()
        c.security.auto_lock_idle_minutes = self._auto_lock.value()
        c.report.auto_generate = self._auto_report.isChecked()
        c.report.time = self._report_time.time().toString("HH:mm")
        c.report.block_minutes = self._block_minutes.value()
        new_keys = self._ai_box.apply(c.ai)
        if self._ai_box.sends_to_cloud(c.ai) and not (
                c.ai.provider == self.ctrl.config.ai.provider and self._ai_box.sends_to_cloud(self.ctrl.config.ai)):
            ok = QMessageBox.question(self, "Gửi dữ liệu lên AI đám mây?",
                                      "Trích đoạn hoạt động (tiêu đề cửa sổ, dự án, ticket) sẽ được gửi tới "
                                      "nhà cung cấp AI khi bạn dùng các tính năng đã bật. Tiếp tục?")
            if ok != QMessageBox.StandardButton.Yes:
                return
        c.integrations.jira_base_url = self._jira.text().strip()
        c.integrations.ticket_projects = [x.strip().upper() for x in self._ticket_projects.text().split(",") if x.strip()]
        rules = []
        for line in _lines(self._rules):
            if "=>" in line:
                match, project = (x.strip() for x in line.split("=>", 1))
                if match and project:
                    rules.append({"match": match, "project": project})
        c.integrations.project_rules = rules
        for provider, key in new_keys.items():
            self.ctrl.set_ai_key(provider, key)
        switching = c.ui_mode != self.ctrl.config.ui_mode
        self.ctrl.apply_config(c)
        if not switching:  # when switching to web, the window hides and the browser opens instead
            QMessageBox.information(self, "Cài đặt", "Đã lưu cài đặt.")
