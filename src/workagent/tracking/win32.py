"""Windows foreground-window probe using ctypes (no pywin32 dependency).

Only reads: foreground window title/class, owning process image name, idle time and whether the
session is locked. No hooks, no keyboard or mouse capture.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass


@dataclass
class WindowSample:
    ts: float
    app: str = ""            # exe basename, lower-case
    title: str = ""
    window_class: str = ""
    hwnd: int = 0
    idle_seconds: float = 0.0
    session_locked: bool = False


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_SWITCHDESKTOP = 0x0100


class Win32Probe:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Win32Probe requires Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u, k = self._user32, self._kernel32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
        u.OpenInputDesktop.restype = wintypes.HANDLE
        u.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        u.SwitchDesktop.argtypes = [wintypes.HANDLE]
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.GetTickCount64.restype = ctypes.c_ulonglong

    def sample(self) -> WindowSample:
        now = time.time()
        idle = self._idle_seconds()
        if self._session_locked():
            return WindowSample(ts=now, idle_seconds=idle, session_locked=True)
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return WindowSample(ts=now, idle_seconds=idle)
        app = self._process_name(hwnd)
        return WindowSample(
            ts=now,
            app=app,
            title=self._text(self._user32.GetWindowTextLengthW(hwnd) + 1,
                             lambda buf, n: self._user32.GetWindowTextW(hwnd, buf, n)),
            window_class=self._text(256, lambda buf, n: self._user32.GetClassNameW(hwnd, buf, n)),
            hwnd=int(hwnd),
            idle_seconds=idle,
            session_locked=app == "lockapp.exe",
        )

    @staticmethod
    def _text(size: int, fill) -> str:
        buf = ctypes.create_unicode_buffer(max(size, 1))
        fill(buf, len(buf))
        return buf.value

    def _idle_seconds(self) -> float:
        info = _LASTINPUTINFO(cbSize=ctypes.sizeof(_LASTINPUTINFO))
        if not self._user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # dwTime is a 32-bit tick count; compare modulo 2**32 to survive the 49-day wrap.
        now = self._kernel32.GetTickCount64() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0

    def _session_locked(self) -> bool:
        desk = self._user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not desk:
            return True  # the input desktop is the secure (Winlogon) desktop
        try:
            return not self._user32.SwitchDesktop(desk)
        finally:
            self._user32.CloseDesktop(desk)

    def _process_name(self, hwnd) -> str:
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        name = ""
        handle = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if handle:
            try:
                size = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(size.value)
                if self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value).lower()
            finally:
                self._kernel32.CloseHandle(handle)
        return name
