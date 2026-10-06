import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from workagent.ai import opencode
from workagent.ai.opencode import OpenCodeProvider
from workagent.ai.providers import (PROVIDERS, AIProviderError, OpenAICompatibleProvider, build_provider,
                                    create_provider, model_for)
from workagent.config import AIConfig, Config, ReportConfig
from workagent.models import ACTIVE, Activity, Task
from workagent.reports.generator import ReportGenerator, activity_log, compose_with_llm

# --- registry & config ------------------------------------------------------------------------

def test_registry_covers_requested_providers():
    for pid in ("mistral", "gemini", "groq", "mangso", "anthropic", "opencode", "openai_compatible", "none"):
        assert pid in PROVIDERS
    assert PROVIDERS["mangso"].base_url == "https://ai.mangso.net/v1"
    assert PROVIDERS["opencode"].models[0] == "opencode/big-pickle"
    assert not PROVIDERS["opencode"].local and PROVIDERS["openai_compatible"].local


def test_model_resolution_and_config_dict_roundtrip(tmp_path):
    cfg = AIConfig(provider="groq", models={"groq": "my-model"})
    assert model_for(cfg, "groq") == "my-model"
    assert model_for(cfg, "mistral") == PROVIDERS["mistral"].models[0]
    path = tmp_path / "c.json"
    c = Config()
    c.ai.models = {"mangso": "x"}
    c.save(path)
    assert Config.load(path).ai.models == {"mangso": "x"}


def test_create_provider_requires_key_and_fixed_urls():
    cfg = AIConfig(provider="gemini")
    with pytest.raises(AIProviderError):
        create_provider(cfg, "gemini", "")
    p = create_provider(cfg, "gemini", "k", base_url="http://evil.example/v1")  # cloud URLs are not overridable
    assert p._base == PROVIDERS["gemini"].base_url and not p.is_local
    local = create_provider(cfg, "openai_compatible", "", base_url="http://127.0.0.1:1234/v1")
    assert local._base == "http://127.0.0.1:1234/v1" and local.is_local
    assert build_provider(AIConfig(provider="none"), lambda p: "") is None
    assert build_provider(AIConfig(provider="groq"), lambda p: "") is None  # no key -> disabled, not crash


# --- OpenAI-compatible HTTP -------------------------------------------------------------------

class _Stub(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer good":
            return self._json(401, {"error": {"message": "Invalid API key"}})
        self._json(200, {"data": [{"id": "models/gemini-x"}, {"id": "m-1"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Stub.seen.append(body)
        self._json(200, {"choices": [{"message": {"content": "OK"}}]})


@pytest.fixture
def stub():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()


def test_openai_compatible_complete_and_models(stub):
    p = OpenAICompatibleProvider(stub, "m-1", "good", timeout=5)
    assert p.complete("sys", "hi") == "OK"
    assert _Stub.seen[-1]["model"] == "m-1" and _Stub.seen[-1]["messages"][0]["role"] == "system"
    assert p.list_models() == ["gemini-x", "m-1"]
    with pytest.raises(AIProviderError, match="401.*Invalid API key"):
        OpenAICompatibleProvider(stub, "m", "bad", timeout=5).list_models()
    with pytest.raises(AIProviderError):
        OpenAICompatibleProvider("http://127.0.0.1:9/v1", "m", timeout=2).complete("s", "p")


# --- OpenCode CLI -----------------------------------------------------------------------------

class FakeProc:
    def __init__(self, events, returncode=0):
        self.stdout = [json.dumps(e).encode() + b"\n" for e in events]
        self.stderr = []
        self.returncode = returncode
        self.killed = False

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.returncode


def _provider(monkeypatch):
    monkeypatch.setattr(opencode, "find_opencode", lambda override="": "C:/fake/opencode.exe")
    return OpenCodeProvider("opencode/big-pickle")


def test_opencode_collects_text_and_dedupes_parts(monkeypatch):
    p = _provider(monkeypatch)
    proc = FakeProc([{"type": "step_start"}, {"type": "text", "part": {"id": "a", "type": "text", "text": "Hel"}},
                     {"type": "text", "part": {"id": "a", "type": "text", "text": "Hello"}},
                     {"type": "text", "part": {"id": "b", "type": "text", "text": " world"}}])
    texts, error, tool = p._collect(proc)
    assert "".join(texts) == "Hello world" and not error and not tool


def test_opencode_kills_on_tool_use(monkeypatch):
    p = _provider(monkeypatch)
    proc = FakeProc([{"type": "tool_use", "part": {"type": "tool", "tool": "webfetch"}},
                     {"type": "text", "part": {"id": "a", "type": "text", "text": "leaked"}}])
    texts, error, tool = p._collect(proc)
    assert tool == "webfetch" and proc.killed and texts == []


def test_opencode_free_tier_falls_back_to_plan_agent(monkeypatch):
    p = _provider(monkeypatch)
    calls = []

    def fake_run(message, deny_tools):
        calls.append(deny_tools)
        if deny_tools:
            raise AIProviderError("Error from provider: OpenCode's free tier can only be used from within OpenCode")
        return "OK"

    monkeypatch.setattr(p, "_run", fake_run)
    assert p.complete("s", "p") == "OK" and calls == [True, False] and p.hardened is False


def test_opencode_error_event(monkeypatch):
    p = _provider(monkeypatch)
    texts, error, tool = p._collect(FakeProc([{"type": "error", "error": {"data": {"message": "quota"}}}], 1))
    assert error == "quota"


def test_opencode_not_installed(monkeypatch):
    monkeypatch.setattr(opencode, "find_opencode", lambda override="": "")
    with pytest.raises(AIProviderError):
        OpenCodeProvider("x")


# --- report composition -----------------------------------------------------------------------

BASE = datetime(2026, 10, 5, 9, 0).timestamp()


def _acts():
    return [Activity(id="a", start=BASE, end=BASE + 5400, kind=ACTIVE, app="code.exe", app_name="VS Code",
                     title="vault.py - dayflow", project="dayflow", tickets=["PROJ-7"], category="development"),
            Activity(id="b", start=BASE + 5400, end=BASE + 5420, kind=ACTIVE, app="x.exe", app_name="X", title="blip"),
            Activity(id="c", start=BASE + 6000, end=BASE + 6600, kind="private", app="keepass.exe")]


GOOD = """```markdown
## 1. Tiến độ hôm nay
- Làm dayflow (PROJ-7) — 1h 30m
  - _Evidence: 09:00–10:30 VS Code vault.py_
## 2. Vấn đề phát hiện
- _None._
## 3. Bị chặn
- _None._
## 4. Cần hỗ trợ / Escalation
- _None._
## 5. Kế hoạch ngày mai
- (inferred) Tiếp tục PROJ-7
```"""


class Echo:
    name = "fake"
    is_local = True

    def __init__(self, reply):
        self.reply, self.prompt = reply, ""

    def complete(self, system, prompt):
        self.system, self.prompt = system, prompt
        return self.reply


def test_activity_log_is_compact_and_private():
    lines = activity_log(_acts())
    assert len(lines) == 2  # 20-second blip dropped
    assert "PROJ-7" in lines[0] and "(private)" in lines[1] and "keepass" not in lines[1]


def test_compose_accepts_grounded_output():
    report = ReportGenerator(ReportConfig()).generate("2026-10-05", _acts(), [])
    llm = Echo(GOOD)
    out = compose_with_llm(report, llm, _acts(), [Task(id="t", title="Ship", ticket="PROJ-7")], "vi")
    assert out.generator == "llm:fake" and not out.ai_error
    assert out.markdown.startswith("# Daily Report — 2026-10-05") and "## 1. Tiến độ hôm nay" in out.markdown
    assert "```" not in out.markdown
    assert "Vietnamese" in llm.system and "untrusted" in llm.system and "PROJ-7" in llm.prompt


@pytest.mark.parametrize("reply, reason", [
    (GOOD.replace("PROJ-7)", "PROJ-999)"), "PROJ-999"),
    ("## 1. Progress\n- stuff", "thiếu"),
])
def test_compose_rejects_ungrounded_output(reply, reason):
    report = ReportGenerator(ReportConfig()).generate("2026-10-05", _acts(), [])
    original = report.markdown
    out = compose_with_llm(report, Echo(reply), _acts(), [], "vi")
    assert out.generator == "rules" and reason in out.ai_error and out.markdown == original


def test_compose_reports_provider_errors():
    class Boom(Echo):
        def complete(self, system, prompt):
            raise AIProviderError("HTTP 429: rate limited")

    report = ReportGenerator(ReportConfig()).generate("2026-10-05", _acts(), [])
    assert "429" in compose_with_llm(report, Boom(""), _acts(), [], "en").ai_error
