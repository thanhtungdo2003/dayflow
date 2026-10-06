"""OpenCode CLI provider: runs `opencode run` non-interactively and returns the model's text.

OpenCode is a coding *agent* with tools (shell, file edits, web fetch). The data we send
contains window titles, which outside parties (web pages, emails) can influence, so a crafted
title could try to steer the agent. Defences, strongest first:

1. Each call runs in a fresh, empty temp directory (no project files to read or modify),
   which is deleted afterwards. The prompt is passed as an argument, never written to disk.
2. Tools are denied through OPENCODE_PERMISSION. OpenCode's free tier (e.g. Big Pickle) rejects
   modified permissions, so for those models we fall back to the built-in read-only `plan`
   agent (no edits or shell commands, but it can still fetch web pages).
3. Output is streamed as JSON events. If the agent starts using any tool, the process is
   killed and the answer discarded.

The UI warns that OpenCode's hosted models (including the free ones) run in the cloud.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from .providers import AIProviderError

log = logging.getLogger(__name__)

MAX_ARG_CHARS = 30_000  # Windows command lines are limited to 32,767 characters
DENY_ALL = json.dumps({"edit": "deny", "bash": "deny", "webfetch": "deny", "external_directory": "deny",
                       "doom_loop": "deny"})
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_opencode(override: str = "") -> str:
    """Path to the real opencode executable ('' if not installed)."""
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    for name in ("opencode.exe", "opencode"):
        found = shutil.which(name)
        if found:
            path = Path(found)
            # npm installs a .cmd/.ps1 shim; prefer the bundled binary so no shell is involved.
            candidates.append(path.parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe")
            candidates.append(path)
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe")
    candidates.append(Path.home() / ".opencode" / "bin" / ("opencode.exe" if sys.platform == "win32" else "opencode"))
    for path in candidates:
        if path.is_file() and path.suffix.lower() not in (".cmd", ".ps1", ".bat"):
            return str(path)
    return ""


def list_models(override: str = "", timeout: int = 60) -> list[str]:
    exe = find_opencode(override)
    if not exe:
        raise AIProviderError("không tìm thấy OpenCode CLI")
    try:
        out = subprocess.run([exe, "models"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AIProviderError(f"không chạy được OpenCode: {type(exc).__name__}") from exc
    models = [line.strip() for line in out.stdout.splitlines() if "/" in line and " " not in line.strip()]
    if not models:
        raise AIProviderError("OpenCode không trả về model nào")
    return models


class OpenCodeProvider:
    name = "opencode"
    is_local = False  # OpenCode's hosted models (incl. Big Pickle) run in the cloud
    _plan_only: set[str] = set()  # models known to reject custom permissions (free tier)

    def __init__(self, model: str, override_path: str = "", timeout: int = 300):
        self._exe = find_opencode(override_path)
        if not self._exe:
            raise AIProviderError("không tìm thấy OpenCode CLI (cài: npm i -g opencode-ai)")
        self._model = model
        self._timeout = timeout
        self.hardened = True  # False when the free tier forced the plan-agent fallback

    def complete(self, system: str, prompt: str) -> str:
        message = f"{system}\n\n{prompt}"
        if len(message) > MAX_ARG_CHARS:
            message = message[:MAX_ARG_CHARS]
        if self._model in self._plan_only:
            self.hardened = False
            return self._run(message, deny_tools=False)
        try:
            self.hardened = True
            return self._run(message, deny_tools=True)
        except AIProviderError as exc:
            if "free tier" not in str(exc).lower():
                raise
            log.info("OpenCode free tier rejects custom permissions; using the read-only plan agent")
            self.hardened = False
            OpenCodeProvider._plan_only.add(self._model)
            return self._run(message, deny_tools=False)

    def _run(self, message: str, deny_tools: bool) -> str:
        args = [self._exe, "run", "--format", "json", "--agent", "plan"]
        if self._model:
            args += ["-m", self._model]
        args.append(message)
        env = dict(os.environ)
        env.pop("OPENCODE_CONFIG_CONTENT", None)
        if deny_tools:
            env["OPENCODE_PERMISSION"] = DENY_ALL
        else:
            env.pop("OPENCODE_PERMISSION", None)
        workdir = tempfile.mkdtemp(prefix="wa-opencode-")
        try:
            proc = subprocess.Popen(args, cwd=workdir, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
            texts, error, tool_used = self._collect(proc)
        except OSError as exc:
            raise AIProviderError(f"không chạy được OpenCode: {type(exc).__name__}") from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if tool_used:
            raise AIProviderError("OpenCode định dùng công cụ (" + tool_used + ") — đã dừng và bỏ kết quả")
        if error:
            raise AIProviderError(error)
        text = "".join(texts).strip()
        if not text:
            raise AIProviderError("OpenCode không trả lời")
        return text

    def _collect(self, proc: subprocess.Popen) -> tuple[list[str], str, str]:
        texts: dict[str, str] = {}  # part id -> latest text (parts may be re-emitted as they grow)
        error = ""
        tool_used = ""
        stderr_lines: list[str] = []
        drain = threading.Thread(target=lambda: stderr_lines.extend(
            line.decode("utf-8", errors="replace") for line in proc.stderr), daemon=True)
        drain.start()  # keep stderr flowing so the child can never block on a full pipe
        timer = threading.Timer(self._timeout, proc.kill)
        timer.start()
        started = time.monotonic()
        try:
            for raw in proc.stdout:
                try:
                    event = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                part = event.get("part") or {}
                if event.get("type") == "error":
                    data = (event.get("error") or {}).get("data") or {}
                    error = str(data.get("message") or event.get("error") or "lỗi OpenCode")[:300]
                elif part.get("type") == "tool" or event.get("type") in ("tool_use", "tool"):
                    tool_used = str(part.get("tool") or "tool")
                    proc.kill()
                    break
                elif part.get("type") == "text" and part.get("text"):
                    texts[str(part.get("id") or len(texts))] = part["text"]
            proc.wait(timeout=10)
            drain.join(timeout=5)
        finally:
            timer.cancel()
        if proc.returncode not in (0, None) and not (error or tool_used or texts):
            stderr = "".join(stderr_lines)
            if time.monotonic() - started >= self._timeout:
                error = "OpenCode quá thời gian chờ"
            else:
                error = (stderr.strip().splitlines() or [f"OpenCode thoát với mã {proc.returncode}"])[-1][:300]
        return list(texts.values()), error, tool_used
