"""Privacy filter: decides what of a window sample may be persisted.

Order of precedence: blocked app > blocked domain > blocked keyword > privacy mode > redaction.
A blocked sample becomes a PRIVATE activity carrying only its duration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from ..config import PrivacyConfig
from ..models import ACTIVE, PRIVATE

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in (
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",            # JWT
    r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_-]{16,}",       # API keys
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",                                           # GitHub tokens
    r"\bxox[abprs]-[A-Za-z0-9-]{10,}",                                         # Slack tokens
    r"\bAKIA[0-9A-Z]{16}\b",                                                   # AWS key id
    r"\bAIza[0-9A-Za-z_-]{30,}",                                               # Google API key
    r"(?i)\b(?:password|passwd|pwd|token|secret|api[_-]?key|apikey)\s*[=:]\s*\S+",
    r"\b[A-Fa-f0-9]{32,}\b",                                                   # long hex
    # random-looking tokens: long, and mixing lower, upper and digits (spares paths/branch names)
    r"\b(?=[A-Za-z0-9+_-]*\d)(?=[A-Za-z0-9+_-]*[a-z])(?=[A-Za-z0-9+_-]*[A-Z])[A-Za-z0-9+_-]{32,}={0,2}",
    r"(?<![\w-])\d{6,8}(?![\w-])",                                             # OTP-like codes
))

REDACTED = "[redacted]"


@dataclass
class FilteredSample:
    kind: str           # ACTIVE or PRIVATE
    app: str
    title: str
    url: str


def _keyword_pattern(words: list[str]) -> re.Pattern[str] | None:
    words = [w.strip().lower() for w in words if w.strip()]
    if not words:
        return None
    alts = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def sanitize_url(url: str, mode: str) -> str:
    if not url or mode == "off":
        return ""
    if "://" not in url:
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:(?!\d)", url):
            return ""  # javascript:, mailto:, data:, file: ...
        url = "https://" + url
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return ""
        host = parts.hostname.lower()
        if mode == "domain":
            return host
        # full: never keep credentials, query or fragment — tokens and session ids live there.
        netloc = host if parts.port is None else f"{host}:{parts.port}"
    except ValueError:
        return ""
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def domain_of(url: str) -> str:
    if not url:
        return ""
    try:
        return (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
    except ValueError:
        return ""


class PrivacyFilter:
    def __init__(self, config: PrivacyConfig):
        self.update(config)

    def update(self, config: PrivacyConfig) -> None:
        self._config = config
        self._apps = {a.strip().lower() for a in config.blocked_apps if a.strip()}
        self._domains = [d.strip().lower().lstrip(".") for d in config.blocked_domains if d.strip()]
        self._keywords = _keyword_pattern(config.blocked_keywords)

    def is_blocked(self, app: str, title: str, url: str = "") -> bool:
        if app.lower() in self._apps:
            return True
        host = domain_of(url)
        if host and any(host == d or host.endswith("." + d) for d in self._domains):
            return True
        haystack = f"{title} {url}"
        if self._keywords and self._keywords.search(haystack):
            return True
        # Domains often appear in titles even when URL capture is off.
        lowered = title.lower()
        return any(d in lowered for d in self._domains)

    def apply(self, app: str, title: str, url: str, privacy_mode: bool) -> FilteredSample:
        app = app.lower()
        if self.is_blocked(app, title, url):
            return FilteredSample(PRIVATE, app, "", "")
        if privacy_mode:
            return FilteredSample(ACTIVE, app, "", "")
        clean_url = sanitize_url(url, self._config.browser_url_mode)
        if self._config.redact_secrets:
            title = redact(title)
            clean_url = redact(clean_url)
        return FilteredSample(ACTIVE, app, title.strip(), clean_url)
