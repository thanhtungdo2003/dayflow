"""Optional browser URL reader via Windows UI Automation.

Disabled unless `privacy.browser_url_mode` is not "off" AND the optional `uiautomation` package
is installed (`pip install .[browser]`). Reads the address bar of Chromium browsers and Firefox
only when the window title changes, and never raises: failures just yield "".
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SUPPORTED = {"chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe", "firefox.exe",
             "coccoc.exe"}


class BrowserUrlReader:
    def __init__(self) -> None:
        try:
            import uiautomation  # type: ignore[import-not-found]
            self._auto = uiautomation
            self._auto.SetGlobalSearchTimeout(0.5)
        except Exception:  # noqa: BLE001 - optional dependency, any import failure disables it
            self._auto = None
        self._initializer = None
        self._cache_key: tuple[int, str] | None = None
        self._cache_url = ""

    @property
    def available(self) -> bool:
        return self._auto is not None

    def read(self, hwnd: int, app: str, title: str) -> str:
        if self._auto is None or app not in SUPPORTED or not hwnd:
            return ""
        key = (hwnd, title)
        if key == self._cache_key:
            return self._cache_url
        url = ""
        try:
            if self._initializer is None:  # COM must be initialised on the collector thread
                self._initializer = self._auto.UIAutomationInitializerInThread()
            window = self._auto.ControlFromHandle(hwnd)
            edit = window.EditControl(searchDepth=16) if window else None
            if edit and edit.Exists(0, 0):
                url = edit.GetValuePattern().Value or ""
        except Exception:  # noqa: BLE001 - UIA is best effort
            log.debug("browser url read failed")
        self._cache_key, self._cache_url = key, url
        return url
