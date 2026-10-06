"""Developer commands. Only needs a system Python 3.11+.

    python tasks.py dev      # create .venv if needed, install, run with ./.devdata and debug logs
    python tasks.py test     # run the test suite
    python tasks.py build    # build dist/PersonalWorkAgent.exe (single file, windowed)
    python tasks.py clean    # remove build artefacts
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
STAMP = VENV / ".installed"


def sh(*args: str, env: dict | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True, env=env)


def ensure_env() -> None:
    if not PY.exists():
        sh(sys.executable, "-m", "venv", str(VENV))
    pyproject = ROOT / "pyproject.toml"
    if not STAMP.exists() or STAMP.stat().st_mtime < pyproject.stat().st_mtime:
        sh(str(PY), "-m", "pip", "install", "--upgrade", "pip", "-q")
        sh(str(PY), "-m", "pip", "install", "-e", ".[dev,ai]", "-q")
        STAMP.touch()


def make_icon() -> Path:
    """Render the app icon to build/icon.ico with Qt (no image assets in the repo)."""
    out = ROOT / "build" / "icon.ico"
    out.parent.mkdir(exist_ok=True)
    code = (
        "import sys; from PySide6.QtWidgets import QApplication; app=QApplication([]);"
        "from workagent.ui.widgets import state_icon; from workagent.ui import theme;"
        f"ok=state_icon(theme.ACCENT, size=256).pixmap(256,256).save(r'{out}', 'ICO'); sys.exit(0 if ok else 1)"
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    try:
        sh(str(PY), "-c", code, env=env)
    except subprocess.CalledProcessError:
        print("warning: could not render icon; building without one")
    return out


def dev() -> None:
    ensure_env()
    env = dict(os.environ, WORKAGENT_HOME=str(ROOT / ".devdata"))
    sh(str(PY), "-m", "workagent", "--debug", *sys.argv[2:], env=env)


def test() -> None:
    ensure_env()
    sh(str(PY), "-m", "pytest", *sys.argv[2:])


def build() -> None:
    exe = ROOT / "dist" / "PersonalWorkAgent.exe"
    if exe.exists():
        try:
            exe.open("ab").close()
        except PermissionError:
            sys.exit("PersonalWorkAgent.exe is running — quit it from the tray icon, then build again.")
    ensure_env()
    test()
    icon = make_icon()
    args = [
        str(PY), "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "PersonalWorkAgent", "--paths", "src",
        "--collect-submodules", "workagent",
        "--hidden-import", "_cffi_backend",
        "--add-data", f"src/workagent/web/static{os.pathsep}workagent/web/static",
    ]
    for module in ("PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
                   "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtMultimedia", "PySide6.QtPdf",
                   "tkinter", "unittest", "pytest"):
        args += ["--exclude-module", module]
    if icon.exists():
        args += ["--icon", str(icon)]
    sh(*args, "packaging/launcher.py")
    print(f"\nBuilt: {ROOT / 'dist' / 'PersonalWorkAgent.exe'}")


def clean() -> None:
    for name in ("build", "dist", "PersonalWorkAgent.spec"):
        path = ROOT / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


COMMANDS = {"dev": dev, "test": test, "build": build, "clean": clean}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    COMMANDS[sys.argv[1]]()
