"""Main window: sidebar navigation + pages; swaps to setup/lock screens by vault state."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QMainWindow, QStackedWidget, QVBoxLayout, QWidget,
)

from ..app import AppController
from ..storage.vault import VaultError, VaultState
from ..tracking.collector import TrackingMode
from .pages.chat import ChatPage
from .pages.dashboard import DashboardPage
from .pages.report import ReportPage
from .pages.settings import SettingsPage
from .pages.tasks import TasksPage
from .pages.timeline import TimelinePage
from .pin_screens import LockScreen, SetupScreen
from .widgets import state_icon
from . import theme

MODE_TEXT = {
    TrackingMode.TRACKING.value: "● Đang theo dõi",
    TrackingMode.PAUSED.value: "❚❚ Tạm dừng",
    TrackingMode.PRIVACY.value: "◐ Chế độ riêng tư",
}


class MainWindow(QMainWindow):
    def __init__(self, ctrl: AppController, tray_available: bool):
        super().__init__()
        self.ctrl = ctrl
        self._tray_available = tray_available
        self._quitting = False
        self._close_hint_shown = False
        self.setWindowTitle("Personal Work Agent")
        self.setWindowIcon(state_icon(theme.ACCENT))
        self.resize(1180, 780)
        self.setMinimumSize(900, 600)

        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 8)
        app_title = QLabel("Work Agent")
        app_title.setObjectName("AppTitle")
        self._status = QLabel("")
        self._status.setObjectName("StatusLine")
        self._status.setWordWrap(True)
        side.addWidget(app_title)
        side.addWidget(self._status)
        self._nav = QListWidget()
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.addWidget(self._nav, 1)
        privacy = QLabel("Chỉ lưu cục bộ · đã mã hoá")
        privacy.setObjectName("Hint")
        privacy.setContentsMargins(16, 0, 16, 0)
        side.addWidget(privacy)
        row.addWidget(sidebar)

        self._pages_stack = QStackedWidget()
        self.pages = [DashboardPage(ctrl), TimelinePage(ctrl), TasksPage(ctrl), ChatPage(ctrl),
                      ReportPage(ctrl), SettingsPage(ctrl)]
        for page in self.pages:
            self._nav.addItem(page.title)
            self._pages_stack.addWidget(page)
        self._nav.currentRowChanged.connect(self._pages_stack.setCurrentIndex)

        self._setup = SetupScreen()
        self._setup.submitted.connect(self._on_setup)
        self._lock = LockScreen(ctrl.unlock, ctrl.vault.pending_writes)
        self._lock.unlocked.connect(lambda _: self._sync_state())

        row.addWidget(self._pages_stack, 1)
        self._outer = QStackedWidget()
        self._outer.addWidget(root)
        self._outer.addWidget(self._setup)
        self._outer.addWidget(self._lock)
        self.setCentralWidget(self._outer)
        self._nav.setCurrentRow(0)

        ctrl.vault_changed.connect(lambda _: self._sync_state())
        ctrl.tracking_changed.connect(lambda _: self._update_status())
        ctrl.activity_changed.connect(self._on_activity)
        ctrl.data_changed.connect(self._schedule_refresh)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(3000)
        self._refresh_timer.timeout.connect(self._refresh_visible)
        self._sync_state()

    # --- state ------------------------------------------------------------------------------

    def _sync_state(self) -> None:
        state = self.ctrl.vault.state
        if state is VaultState.UNINITIALIZED:
            self._outer.setCurrentWidget(self._setup)
        elif state is VaultState.LOCKED:
            self._outer.setCurrentWidget(self._lock)
        else:
            self._outer.setCurrentWidget(self._outer.widget(0))
            self._refresh_visible()
        self._update_status()

    def _update_status(self) -> None:
        mode = MODE_TEXT.get(self.ctrl.tracking_mode.value, "")
        if self.ctrl.tracking_error:
            mode = "Không thể theo dõi"
        elif not self.ctrl.tracking_started:
            mode = "Chưa bắt đầu theo dõi"
        vault = {"unlocked": "Đã mở khoá", "locked": "🔒 Đã khoá", "uninitialized": "Chưa thiết lập"}[
            self.ctrl.vault.state.value]
        self._status.setText(f"{mode}\n{vault}")

    def _on_setup(self, pin: str, run_at_startup: bool) -> None:
        try:
            self.ctrl.setup_vault(pin, run_at_startup)
            self._setup.clear()
        except VaultError as exc:
            self._setup.show_error(str(exc))

    def _on_activity(self, act) -> None:
        page = self._pages_stack.currentWidget()
        if isinstance(page, DashboardPage) and self.ctrl.vault.is_unlocked:
            page.update_now(act)

    def _schedule_refresh(self) -> None:
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _refresh_visible(self) -> None:
        if not self.isVisible() or not self.ctrl.vault.is_unlocked:
            return
        page = self._pages_stack.currentWidget()
        if isinstance(page, (DashboardPage, TimelinePage)):
            page.refresh()

    def show_page(self, page_type, **kwargs) -> None:
        for i, page in enumerate(self.pages):
            if isinstance(page, page_type):
                self._nav.setCurrentRow(i)
                if isinstance(page, ReportPage) and "day" in kwargs:
                    page.show_day(kwargs["day"])
        self.bring_to_front()

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # --- window behaviour -------------------------------------------------------------------

    def quit(self) -> None:
        self._quitting = True
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._quitting or not self._tray_available:
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._close_hint_shown:
            self._close_hint_shown = True
            self.ctrl.notify.emit("Vẫn đang chạy", "Ứng dụng vẫn theo dõi dưới khay hệ thống. Dùng menu khay để thoát.")
