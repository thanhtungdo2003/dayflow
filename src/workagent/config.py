"""Application configuration.

Stored as plaintext JSON in the data dir, so it must only hold non-sensitive settings.
Secrets (API keys) live in the vault (see SecretRepository).
Unknown keys are ignored and missing keys fall back to defaults, so old files keep working.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class TrackingConfig:
    sample_seconds: float = 2.0
    idle_seconds: int = 180          # no input for this long -> "away"
    min_activity_seconds: float = 3.0
    flush_seconds: float = 30.0
    start_paused: bool = False


@dataclass
class PrivacyConfig:
    browser_url_mode: str = "off"    # off | domain | full (query/fragment always dropped)
    redact_secrets: bool = True
    blocked_apps: list[str] = field(default_factory=lambda: [
        "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe",
        "dashlane.exe", "enpass.exe", "nordpass.exe", "authy desktop.exe", "winauth.exe",
        "credentialuibroker.exe", "consent.exe", "logonui.exe", "lockapp.exe",
    ])
    blocked_keywords: list[str] = field(default_factory=lambda: [
        "password", "passwords", "passwd", "mật khẩu", "otp", "2fa", "two-factor", "authenticator",
        "verification code", "mã xác thực", "private key", "seed phrase", "recovery phrase",
        "id_rsa", ".pem", ".env", "secret", "banking", "ngân hàng", "inprivate", "incognito",
        "private browsing",
    ])
    blocked_domains: list[str] = field(default_factory=lambda: [
        "paypal.com", "accounts.google.com", "login.microsoftonline.com", "vietcombank.com.vn",
        "techcombank.com.vn", "mbbank.com.vn", "vpbank.com.vn", "bidv.com.vn", "momo.vn",
    ])


@dataclass
class SecurityConfig:
    lock_on_windows_lock: bool = True
    auto_lock_idle_minutes: int = 15   # 0 = never
    kdf_time_cost: int = 3
    kdf_memory_kib: int = 64 * 1024
    kdf_parallelism: int = 4


@dataclass
class ReportConfig:
    auto_generate: bool = True
    time: str = "17:30"               # local HH:MM
    min_project_minutes: int = 10
    block_minutes: int = 45            # same issue investigated this long -> possible blocker


@dataclass
class AIConfig:
    provider: str = "none"             # see ai.providers.PROVIDERS (none, mistral, gemini, groq, mangso, …)
    base_url: str = "http://localhost:11434/v1"   # only for the editable local/OpenAI-compatible provider
    model: str = ""                    # legacy single model; per-provider choices live in `models`
    models: dict[str, str] = field(default_factory=dict)
    allow_chat: bool = False           # send retrieved context with chat questions
    allow_reports: bool = False        # send activity evidence for report writing
    report_mode: str = "compose"       # compose (AI writes from the log) | polish (AI rewords rule items)
    report_language: str = "vi"        # language the AI writes the report in: vi | en
    timeout_seconds: int = 90
    opencode_path: str = ""            # empty = auto-detect the installed CLI
    opencode_timeout_seconds: int = 300


@dataclass
class IntegrationConfig:
    jira_base_url: str = ""            # e.g. https://yourcompany.atlassian.net
    ticket_projects: list[str] = field(default_factory=list)  # restrict ticket keys, e.g. ["PROJ"]
    project_rules: list[dict[str, str]] = field(default_factory=list)  # [{"match": "...", "project": "..."}]


@dataclass
class Config:
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    integrations: IntegrationConfig = field(default_factory=IntegrationConfig)
    ui_mode: str = "desktop"          # desktop | web (local browser UI on 127.0.0.1)
    web_port: int = 8765
    run_at_startup: bool = True
    start_minimized: bool = True
    debug: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        return _merge(cls(), data)

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            log.warning("config unreadable, using defaults: %s", type(exc).__name__)
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)


def _merge(target: Any, data: dict[str, Any]) -> Any:
    if not isinstance(data, dict):
        return target
    for f in fields(target):
        if f.name not in data:
            continue
        current, value = getattr(target, f.name), data[f.name]
        if is_dataclass(current):
            _merge(current, value)
        elif isinstance(current, bool):
            if isinstance(value, bool):
                setattr(target, f.name, value)
        elif isinstance(current, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(target, f.name, type(current)(value))
        elif isinstance(current, str):
            if isinstance(value, str):
                setattr(target, f.name, value)
        elif isinstance(current, list):
            if isinstance(value, list):
                setattr(target, f.name, value)
        elif isinstance(current, dict):
            if isinstance(value, dict):
                setattr(target, f.name, {str(k): str(v) for k, v in value.items() if isinstance(v, (str, int, float))})
    return target
