from datetime import datetime

from workagent.config import PrivacyConfig
from workagent.context.extractor import ContextExtractor
from workagent.models import ACTIVE, AWAY, LOCKED, PRIVATE
from workagent.tracking.coalescer import Coalescer, Observation
from workagent.tracking.collector import Collector, TrackingMode
from workagent.tracking.privacy import PrivacyFilter, redact, sanitize_url
from workagent.tracking.win32 import WindowSample

T0 = datetime(2026, 10, 5, 9, 0, 0).timestamp()


# --- privacy ----------------------------------------------------------------------------------

def test_blocked_apps_keywords_and_domains():
    f = PrivacyFilter(PrivacyConfig())
    assert f.apply("KeePassXC.exe", "Database.kdbx", "", False).kind == PRIVATE
    assert f.apply("chrome.exe", "Reset your password - Google Chrome", "", False).kind == PRIVATE
    assert f.apply("chrome.exe", "Vietcombank Digibank", "https://vcbdigibank.vietcombank.com.vn/x", False).kind == PRIVATE
    assert f.apply("msedge.exe", "New InPrivate tab - Microsoft Edge", "", False).kind == PRIVATE
    blocked = f.apply("chrome.exe", "Your OTP code", "", False)
    assert blocked.title == "" and blocked.url == ""


def test_keyword_matching_uses_word_boundaries():
    f = PrivacyFilter(PrivacyConfig())
    assert f.apply("code.exe", "hotpot.py - kitchen - Visual Studio Code", "", False).kind == ACTIVE
    assert f.apply("code.exe", "process.env usage - Visual Studio Code", "", False).kind == ACTIVE
    assert f.apply("code.exe", ".env - api - Visual Studio Code", "", False).kind == PRIVATE


def test_privacy_mode_keeps_only_app():
    f = PrivacyFilter(PrivacyConfig())
    out = f.apply("code.exe", "main.py - proj - Visual Studio Code", "https://x.dev", True)
    assert out.kind == ACTIVE and out.app == "code.exe" and out.title == "" and out.url == ""


def test_redaction_of_secrets():
    assert "[redacted]" in redact("token=abc123def456")
    assert "ghp_" not in redact("ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert "eyJ" not in redact("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N")
    assert "482913" not in redact("Your code is 482913")
    # Non-secrets stay readable
    assert redact("PROJ-1234 Fix login") == "PROJ-1234 Fix login"
    assert redact("D:/MyProjects/dayflow/src/workagent/tracking") == "D:/MyProjects/dayflow/src/workagent/tracking"
    assert redact("feature/my-very-long-branch-name-for-the-login-flow") == \
        "feature/my-very-long-branch-name-for-the-login-flow"


def test_url_sanitising():
    url = "https://user:pw@github.com/org/repo/pull/1?token=abc#frag"
    assert sanitize_url(url, "off") == ""
    assert sanitize_url(url, "domain") == "github.com"
    assert sanitize_url(url, "full") == "https://github.com/org/repo/pull/1"
    assert sanitize_url("javascript:alert(1)", "full") == ""


# --- coalescer --------------------------------------------------------------------------------

def _coalescer(**kw):
    return Coalescer(ContextExtractor(), idle_seconds=kw.get("idle", 60), min_activity_seconds=3,
                     flush_seconds=kw.get("flush", 30), max_gap_seconds=10)


def _obs(t, title="a.py - proj - Visual Studio Code", app="code.exe", idle=0.0, locked=False):
    return Observation(ts=T0 + t, kind=ACTIVE, app=app, title=title, idle_seconds=idle,
                       session_locked=locked)


def test_coalesces_same_window_and_splits_on_change():
    c = _coalescer(flush=1000)
    out = []
    for t in range(0, 20, 2):
        out += c.feed(_obs(t))
    assert out == []
    out += c.feed(_obs(20, title="b.py - proj - Visual Studio Code"))
    assert len(out) == 1
    a = out[0]
    assert a.start == T0 and a.end == T0 + 20 and a.project == "proj" and a.file == "a.py"


def test_short_blips_are_dropped():
    c = _coalescer(flush=1000)
    out = c.feed(_obs(0))
    out += c.feed(_obs(2, title="popup"))
    out += c.feed(_obs(3))
    assert all(a.title != "popup" for a in out)


def test_periodic_flush_upserts_same_id():
    c = _coalescer(flush=10)
    out = []
    for t in range(0, 32, 2):
        out += c.feed(_obs(t))
    assert len(out) >= 2 and len({a.id for a in out}) == 1
    assert out[-1].end > out[0].end


def test_idle_is_backdated():
    c = _coalescer(idle=60)
    out = []
    for t in range(0, 132, 2):  # last input at t=60; idle reaches 60 s at t=120
        out += c.feed(_obs(t, idle=max(0, t - 60)))
    active = [a for a in out if a.kind == ACTIVE][-1]
    assert active.end == T0 + 60
    assert c.current.kind == AWAY and c.current.start == T0 + 60


def test_session_lock_creates_locked_activity():
    c = _coalescer()
    c.feed(_obs(0))
    c.feed(_obs(10))
    c.feed(_obs(12, locked=True))
    assert c.current.kind == LOCKED


def test_gap_closes_activity_at_last_seen():
    c = _coalescer()
    c.feed(_obs(0))
    c.feed(_obs(8))
    out = c.feed(_obs(500))  # machine slept
    assert out[0].end == T0 + 8
    assert c.current.start == T0 + 500


def test_midnight_split():
    start = datetime(2026, 10, 5, 23, 59, 50).timestamp()
    c = Coalescer(ContextExtractor(), flush_seconds=1000, max_gap_seconds=10)
    out = []
    for t in range(0, 20, 2):
        out += c.feed(Observation(ts=start + t, kind=ACTIVE, app="code.exe", title="x.py - p - Visual Studio Code"))
    assert len(out) == 1
    assert out[0].day == "2026-10-05" and out[0].end == datetime(2026, 10, 6).timestamp()
    assert c.current.day == "2026-10-06"


def test_midnight_split_while_away_does_not_loop():
    start = datetime(2026, 10, 5, 23, 59, 0).timestamp()
    c = Coalescer(ContextExtractor(), idle_seconds=60, flush_seconds=1000, max_gap_seconds=10)
    out = []
    for t in range(0, 180, 2):
        out += c.feed(Observation(ts=start + t, kind=ACTIVE, app="code.exe", title="x", idle_seconds=100 + t))
    assert len(out) == 1  # one closed span before midnight, nothing repeated
    assert c.current.day == "2026-10-06"


# --- collector --------------------------------------------------------------------------------

class FakeProbe:
    def __init__(self):
        self.t = T0
        self.title = "a.py - proj - Visual Studio Code"

    def sample(self):
        self.t += 2
        return WindowSample(ts=self.t, app="code.exe", title=self.title)


def test_collector_modes():
    stored = []
    probe = FakeProbe()
    col = Collector(probe, PrivacyFilter(PrivacyConfig()), _coalescer(flush=1000), stored.append)
    for _ in range(5):
        col.tick()
    col.set_mode(TrackingMode.PAUSED)          # closes the open activity
    assert len(stored) == 1
    for _ in range(5):
        col.tick()
    assert len(stored) == 1                    # nothing recorded while paused
    col.set_mode(TrackingMode.PRIVACY)
    for _ in range(5):
        col.tick()
    col.stop()
    assert stored[-1].title == "" and stored[-1].app == "code.exe"


def test_collector_listener_never_receives_raw_titles():
    seen = []
    probe = FakeProbe()
    probe.title = "Reset password - Google Chrome"
    col = Collector(probe, PrivacyFilter(PrivacyConfig()), _coalescer(), lambda a: None,
                    on_sample=lambda locked, idle, cur: seen.append(cur))
    col.tick()
    col.tick()
    assert seen[-1].kind == PRIVATE and seen[-1].title == ""
