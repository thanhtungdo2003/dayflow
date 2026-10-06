"""Qt bootstrap: single instance, logging, controller, window, tray."""

from __future__ import annotations

import getpass
import hashlib
import logging
import sys
import webbrowser
from datetime import date

from PySide6.QtCore import QLocale, QLockFile, QObject, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .. import __version__
from ..app import AppController
from ..config import Config
from ..logging_setup import setup_logging
from ..paths import config_path, data_dir, vault_path
from ..storage.vault import Vault, VaultError
from ..web.api import WebApi
from ..web.server import WebServer
from . import theme
from .main_window import MainWindow
from .tray import Tray
from .widgets import state_icon

log = logging.getLogger(__name__)


def _server_name() -> str:
    key = f"{getpass.getuser()}|{data_dir()}".encode()
    return "PersonalWorkAgent-" + hashlib.sha256(key).hexdigest()[:16]


def _signal_existing_instance(name: str) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(500):
        socket.write(b"show")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return True
    return False


class UiRouter(QObject):
    """Opens whichever UI the user chose (desktop window or local web UI) and switches live."""

    def __init__(self, ctrl: AppController, window: MainWindow):
        super().__init__()
        self.ctrl = ctrl
        self.window = window
        self.web = WebServer(WebApi(ctrl), ctrl.config.web_port)
        ctrl.ui_mode_changed.connect(self._on_mode_changed)
        if ctrl.config.ui_mode == "web":
            self._start_web()

    @property
    def web_active(self) -> bool:
        return self.ctrl.config.ui_mode == "web" and self.web.running

    def open(self, view: str = "") -> None:
        if self.web_active:
            webbrowser.open(self.web.url(view))
        else:
            self.window.bring_to_front()

    def open_report(self) -> None:
        if self.web_active:
            self.open("report")
        else:
            from .pages.report import ReportPage
            self.window.show_page(ReportPage, day=date.today().isoformat())

    def _start_web(self) -> None:
        if not self.web.start():
            self.ctrl.notify.emit("Giao diện web", "Không mở được cổng web; dùng giao diện ứng dụng.")

    def _on_mode_changed(self, mode: str) -> None:
        if mode == "web":
            self._start_web()
            self.window.hide()
            self.open()
        else:
            QTimer.singleShot(1500, self.web.stop)  # let the request that switched modes finish
            self.window.bring_to_front()

    def shutdown(self) -> None:
        self.web.stop()


def run(start_minimized: bool = False, debug: bool = False) -> int:
    cfg_path = config_path()
    config = Config.load(cfg_path)
    setup_logging(debug or config.debug)
    log.info("starting Personal Work Agent %s", __version__)

    app = QApplication(sys.argv)
    app.setApplicationName("Personal Work Agent")
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setPalette(theme.light_palette())
    QLocale.setDefault(QLocale(QLocale.Language.Vietnamese, QLocale.Country.Vietnam))
    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(state_icon(theme.ACCENT))

    lock = QLockFile(str(data_dir() / "instance.lock"))
    if not lock.tryLock(100):
        if _signal_existing_instance(_server_name()):
            log.info("another instance is running; asked it to show its window")
            return 0
        lock.removeStaleLockFile()
        if not lock.tryLock(100):
            QMessageBox.warning(None, "Personal Work Agent", "Ứng dụng có vẻ đang chạy ở một phiên khác.")
            return 1

    try:
        vault = Vault(vault_path(), kdf_defaults={
            "time_cost": config.security.kdf_time_cost,
            "memory_kib": config.security.kdf_memory_kib,
            "parallelism": config.security.kdf_parallelism,
        }).open()
    except (VaultError, OSError) as exc:
        log.exception("could not open vault")
        QMessageBox.critical(None, "Personal Work Agent", f"Không mở được kho dữ liệu: {exc}")
        return 1

    ctrl = AppController(config, cfg_path, vault)
    tray_ok = QSystemTrayIcon.isSystemTrayAvailable()
    window = MainWindow(ctrl, tray_available=tray_ok)
    router = UiRouter(ctrl, window)
    tray = Tray(ctrl, window, router) if tray_ok else None
    if tray:
        tray.show()

    server = QLocalServer()
    QLocalServer.removeServer(_server_name())
    server.listen(_server_name())
    server.newConnection.connect(lambda: (server.nextPendingConnection(), router.open()))

    ctrl.start()
    minimized = (start_minimized or config.start_minimized) and tray_ok
    if not minimized or vault.state.value == "uninitialized":
        router.open()

    def shutdown() -> None:
        router.shutdown()
        ctrl.shutdown()
        server.close()
        lock.unlock()

    app.aboutToQuit.connect(shutdown)
    return app.exec()

