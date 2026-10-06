"""System tray icon and menu."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..app import AppController
from ..tracking.collector import TrackingMode
from . import theme
from .widgets import state_icon

COLORS = {
    TrackingMode.TRACKING.value: theme.GOOD,
    TrackingMode.PAUSED.value: theme.WARN,
    TrackingMode.PRIVACY.value: theme.TEXT_2,
}


class Tray(QSystemTrayIcon):
    def __init__(self, ctrl: AppController, window, router):
        super().__init__()
        self.ctrl = ctrl
        self.window = window
        self.router = router
        menu = QMenu()
        self._state = QAction("")
        self._state.setEnabled(False)
        menu.addAction(self._state)
        menu.addSeparator()
        open_action = menu.addAction("Mở cửa sổ")
        open_action.triggered.connect(lambda: router.open())
        self._pause = menu.addAction("Tạm dừng theo dõi")
        self._pause.triggered.connect(self._toggle_pause)
        self._privacy = menu.addAction("Chế độ riêng tư (chỉ ghi tên ứng dụng)")
        self._privacy.setCheckable(True)
        self._privacy.triggered.connect(self._toggle_privacy)
        menu.addSeparator()
        self._lock = menu.addAction("Khoá kho dữ liệu")
        self._lock.triggered.connect(self._lock_or_unlock)
        report = menu.addAction("Báo cáo hôm nay…")
        report.triggered.connect(self._open_report)
        menu.addSeparator()
        quit_action = menu.addAction("Thoát")
        quit_action.triggered.connect(window.quit)
        self.setContextMenu(menu)
        self._menu = menu
        self.activated.connect(self._on_activated)
        ctrl.tracking_changed.connect(lambda _: self.refresh())
        ctrl.vault_changed.connect(lambda _: self.refresh())
        ctrl.notify.connect(lambda title, msg: self.showMessage(title, msg, QSystemTrayIcon.MessageIcon.Information, 5000))
        self.refresh()

    def refresh(self) -> None:
        mode = self.ctrl.tracking_mode.value
        unlocked = self.ctrl.vault.is_unlocked
        self.setIcon(state_icon(COLORS.get(mode, theme.TEXT_2), locked=not unlocked))
        labels = {"tracking": "Đang theo dõi", "paused": "Tạm dừng", "privacy": "Chế độ riêng tư"}
        vault = "đã mở khoá" if unlocked else "đang khoá"
        self._state.setText(f"{labels.get(mode, mode)} · kho {vault}")
        self.setToolTip(f"Personal Work Agent — {labels.get(mode, mode)}, kho {vault}")
        self._pause.setText("Tiếp tục theo dõi" if mode == "paused" else "Tạm dừng theo dõi")
        self._privacy.setChecked(mode == "privacy")
        self._lock.setText("Khoá kho dữ liệu" if unlocked else "Mở khoá…")

    def _toggle_pause(self) -> None:
        paused = self.ctrl.tracking_mode is TrackingMode.PAUSED
        self.ctrl.set_tracking_mode(TrackingMode.TRACKING if paused else TrackingMode.PAUSED)

    def _toggle_privacy(self, checked: bool) -> None:
        self.ctrl.set_tracking_mode(TrackingMode.PRIVACY if checked else TrackingMode.TRACKING)

    def _lock_or_unlock(self) -> None:
        if self.ctrl.vault.is_unlocked:
            self.ctrl.lock()
        else:
            self.router.open()

    def _open_report(self) -> None:
        self.router.open_report()

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger):
            self.router.open()
