"""First-run vault setup and the lock screen."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ..storage.vault import MIN_PIN_LENGTH, VaultError, WrongPinError


def _card(parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
    outer = QVBoxLayout(parent)
    outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
    card = QFrame()
    card.setObjectName("Card")
    card.setFixedWidth(420)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(10)
    outer.addWidget(card)
    return card, layout


def _pin_field(placeholder: str) -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setPlaceholderText(placeholder)
    field.setMinimumHeight(34)
    return field


def pin_strength_hint(pin: str) -> str:
    if len(pin) < MIN_PIN_LENGTH:
        return f"Tối thiểu {MIN_PIN_LENGTH} ký tự."
    if pin.isdigit() and len(pin) < 10:
        return "PIN toàn số vẫn dùng được, nhưng cụm mật khẩu dài hơn khó bị dò thử hơn rất nhiều."
    return "Tốt."


class SetupScreen(QWidget):
    submitted = Signal(str, bool)   # pin, run_at_startup

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        _, layout = _card(self)
        title = QLabel("Tạo kho dữ liệu riêng")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        intro = QLabel("Mọi dữ liệu ứng dụng ghi lại đều được mã hoá trên máy này bằng khoá sinh ra từ PIN "
                       "của bạn. Không có gì được tải lên.")
        intro.setWordWrap(True)
        intro.setObjectName("Muted")
        layout.addWidget(intro)
        self._pin = _pin_field("PIN hoặc cụm mật khẩu")
        self._confirm = _pin_field("Nhập lại PIN")
        self._hint = QLabel(pin_strength_hint(""))
        self._hint.setObjectName("Hint")
        self._hint.setWordWrap(True)
        self._pin.textChanged.connect(lambda t: self._hint.setText(pin_strength_hint(t)))
        layout.addWidget(self._pin)
        layout.addWidget(self._confirm)
        layout.addWidget(self._hint)
        warning = QLabel("<b>Không có cách khôi phục.</b> Nếu quên PIN, không ai có thể giải mã lịch sử "
                         "của bạn — kể cả chính bạn.")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self._startup = QCheckBox("Tự khởi động khi đăng nhập Windows")
        self._startup.setChecked(True)
        layout.addWidget(self._startup)
        self._error = QLabel("")
        self._error.setObjectName("Error")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)
        button = QPushButton("Tạo kho và bắt đầu theo dõi")
        button.setObjectName("Primary")
        button.clicked.connect(self._submit)
        self._confirm.returnPressed.connect(self._submit)
        layout.addWidget(button)

    def _submit(self) -> None:
        pin, confirm = self._pin.text(), self._confirm.text()
        if len(pin) < MIN_PIN_LENGTH:
            self._error.setText(f"Cần ít nhất {MIN_PIN_LENGTH} ký tự.")
            return
        if pin != confirm:
            self._error.setText("Hai lần nhập không khớp.")
            return
        self._error.setText("")
        self.submitted.emit(pin, self._startup.isChecked())

    def show_error(self, text: str) -> None:
        self._error.setText(text)

    def clear(self) -> None:
        self._pin.clear()
        self._confirm.clear()


class LockScreen(QWidget):
    unlocked = Signal(int)          # number of migrated locked-time writes

    def __init__(self, try_unlock, pending_count, parent: QWidget | None = None):
        super().__init__(parent)
        self._try_unlock = try_unlock
        self._pending_count = pending_count
        self._failures = 0
        self._blocked_until = 0.0
        _, layout = _card(self)
        title = QLabel("Kho dữ liệu đang khoá")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        self._info = QLabel("")
        self._info.setObjectName("Muted")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)
        self._pin = _pin_field("Nhập PIN")
        self._pin.returnPressed.connect(self._submit)
        layout.addWidget(self._pin)
        self._error = QLabel("")
        self._error.setObjectName("Error")
        self._error.setWordWrap(True)
        layout.addWidget(self._error)
        self._button = QPushButton("Mở khoá")
        self._button.setObjectName("Primary")
        self._button.clicked.connect(self._submit)
        layout.addWidget(self._button)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh_backoff)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        pending = self._pending_count()
        self._info.setText("Ứng dụng vẫn theo dõi khi khoá; hoạt động mới được ghi ở dạng mã hoá và "
                           "chỉ đọc được sau khi mở khoá."
                           + (f"\nCó {pending} bản ghi đang chờ gộp." if pending else ""))
        self._pin.setFocus()

    def _submit(self) -> None:
        if time.monotonic() < self._blocked_until:
            return
        pin = self._pin.text()
        if not pin:
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            migrated = self._try_unlock(pin)
        except WrongPinError:
            self._failures += 1
            # Slows down guessing at the screen; offline attacks are bounded by Argon2id instead.
            delay = 0 if self._failures < 3 else min(300, 2 ** (self._failures - 2))
            self._blocked_until = time.monotonic() + delay
            self._error.setText("Sai PIN." + (f" Thử lại sau {delay} giây." if delay else ""))
            self._pin.selectAll()
            if delay:
                self._button.setEnabled(False)
                self._timer.start()
            return
        except VaultError as exc:
            self._error.setText(f"Lỗi kho dữ liệu: {exc}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
            QApplication.processEvents()
        self._failures = 0
        self._error.setText("")
        self._pin.clear()
        self.unlocked.emit(migrated)

    def _refresh_backoff(self) -> None:
        remaining = self._blocked_until - time.monotonic()
        if remaining <= 0:
            self._timer.stop()
            self._button.setEnabled(True)
            self._error.setText("Sai PIN.")
        else:
            self._error.setText(f"Sai PIN. Thử lại sau {int(remaining) + 1} giây.")
