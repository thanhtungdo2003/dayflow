import http.client
import json
from datetime import datetime

import pytest
from PySide6.QtCore import QCoreApplication

from workagent.app import AppController
from workagent.config import Config
from workagent.models import Activity
from workagent.storage.vault import Vault
from workagent.system import startup
from workagent.web.api import WebApi
from workagent.web.server import WebServer

from .conftest import FAST_KDF, PIN


class StubApi:
    def handle(self, method, path, query, body):
        return 200, {"method": method, "path": path, "query": query, "body": body}


@pytest.fixture
def server():
    srv = WebServer(StubApi(), port=0)
    assert srv.start()
    yield srv
    srv.stop()


def request(srv, method, path, headers=None, body=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    hdrs = {"Host": host or f"127.0.0.1:{srv.port}", **(headers or {})}
    conn.request(method, path, body=body, headers=hdrs)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def test_static_and_security_headers(server):
    resp, data = request(server, "GET", "/")
    assert resp.status == 200 and b"/app.js" in data
    assert "default-src 'none'" in resp.getheader("Content-Security-Policy")
    assert resp.getheader("X-Frame-Options") == "DENY"
    assert resp.getheader("Cache-Control") == "no-store"
    for path in ("/app.js", "/app.css"):
        assert request(server, "GET", path)[0].status == 200


def test_only_allow_listed_files_are_served(server):
    for path in ("/../vault.db", "/static/../server.py", "/server.py", "/%2e%2e/config.json", "/index.html"):
        assert request(server, "GET", path)[0].status == 404


def test_api_requires_token(server):
    assert request(server, "GET", "/api/state")[0].status == 401
    assert request(server, "GET", "/api/state", {"X-WA-Token": "wrong"})[0].status == 401
    resp, data = request(server, "GET", "/api/state?x=1", {"X-WA-Token": server.token})
    assert resp.status == 200 and json.loads(data)["query"] == {"x": "1"}


def test_dns_rebinding_and_cross_origin_rejected(server):
    tok = {"X-WA-Token": server.token}
    assert request(server, "GET", "/api/state", tok, host=f"evil.example:{server.port}")[0].status == 421
    assert request(server, "GET", "/", host="evil.example")[0].status == 421
    assert request(server, "GET", "/api/state", {**tok, "Origin": "http://evil.example"})[0].status == 403
    assert request(server, "GET", "/api/state", {**tok, "Origin": f"http://127.0.0.1:{server.port}"})[0].status == 200
    assert request(server, "OPTIONS", "/api/state")[0].status == 403  # CORS preflight never approved


def test_body_must_be_json(server):
    tok = {"X-WA-Token": server.token}
    assert request(server, "POST", "/api/lock", {**tok, "Content-Type": "text/plain"}, body="x")[0].status == 415
    assert request(server, "POST", "/api/lock", {**tok, "Content-Type": "application/json"}, body="[1]")[0].status == 400
    resp, data = request(server, "POST", "/api/lock", {**tok, "Content-Type": "application/json"}, body='{"a": 1}')
    assert resp.status == 200 and json.loads(data)["body"] == {"a": 1}


def test_url_carries_token_in_fragment_only(server):
    url = server.url("report")
    assert url.startswith(f"http://127.0.0.1:{server.port}/#t=") and url.endswith("&v=report")


# --- API over a real controller ----------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(AppController, "_start_collector", lambda self: None)
    monkeypatch.setattr(startup, "set_enabled", lambda enabled: True)
    vault = Vault(tmp_path / "vault.db", kdf_defaults=FAST_KDF).open()
    ctrl = AppController(Config(), tmp_path / "config.json", vault)
    yield WebApi(ctrl)
    vault.close()


def call(api, method, path, body=None, **query):
    return api.handle(method, path, {k: str(v) for k, v in query.items()}, body or {})


def test_setup_unlock_lock_flow(api):
    assert call(api, "GET", "/api/state")[1]["vault"] == "uninitialized"
    assert call(api, "POST", "/api/setup", {"pin": "123"})[0] == 400
    assert call(api, "POST", "/api/setup", {"pin": PIN})[0] == 200
    assert call(api, "POST", "/api/setup", {"pin": PIN})[0] == 409
    assert call(api, "GET", "/api/state")[1]["vault"] == "unlocked"
    assert call(api, "POST", "/api/lock")[0] == 200
    assert call(api, "GET", "/api/day")[0] == 423
    state = call(api, "GET", "/api/state")[1]
    assert state["vault"] == "locked" and state["current"] is None
    status, body = call(api, "POST", "/api/unlock", {"pin": "nope-nope"})
    assert status == 403 and body["error"] == "wrong_pin"
    assert call(api, "POST", "/api/unlock", {"pin": PIN})[0] == 200


def test_unlock_throttling(api):
    call(api, "POST", "/api/setup", {"pin": PIN})
    call(api, "POST", "/api/lock")
    for _ in range(2):
        assert call(api, "POST", "/api/unlock", {"pin": "wrong-pin"})[1]["retry_after"] == 0
    status, body = call(api, "POST", "/api/unlock", {"pin": "wrong-pin"})
    assert status == 403 and body["retry_after"] > 0
    status, body = call(api, "POST", "/api/unlock", {"pin": PIN})  # even the right PIN waits
    assert status == 429 and body["retry_after"] > 0


def test_day_tasks_report_settings(api):
    call(api, "POST", "/api/setup", {"pin": PIN})
    day = datetime.now().strftime("%Y-%m-%d")
    base = datetime.strptime(day, "%Y-%m-%d").timestamp() + 9 * 3600
    api.ctrl.activities.upsert(Activity(id="a1", start=base, end=base + 3600, app="code.exe", app_name="VS Code",
                                        title="vault.py - dayflow", category="development", project="dayflow",
                                        tickets=["PROJ-1"]))
    status, d = call(api, "GET", "/api/day", date=day)
    assert status == 200 and d["summary"]["active"] == 3600 and d["sessions"][0]["ids"] == ["a1"]
    assert call(api, "GET", "/api/day", date="not-a-date")[0] == 400

    assert call(api, "POST", "/api/tasks", {"title": ""})[0] == 400
    task = call(api, "POST", "/api/tasks", {"title": "Ship", "status": "doing", "ticket": "proj-1"})[1]["task"]
    assert task["ticket"] == "PROJ-1"
    tasks = call(api, "GET", "/api/tasks")[1]["tasks"]
    assert tasks[0]["tracked"] == 3600
    done = call(api, "POST", "/api/tasks", {**task, "status": "done"})[1]["task"]
    assert done["done_at"] and done["id"] == task["id"]
    assert call(api, "GET", "/api/tickets")[1]["tickets"] == [{"ticket": "PROJ-1", "seconds": 3600, "has_task": True}]
    call(api, "DELETE", "/api/tasks", id=task["id"])
    assert call(api, "GET", "/api/tasks")[1]["tasks"] == []

    assert call(api, "GET", "/api/report", date=day)[1]["report"] is None
    draft = call(api, "POST", "/api/report/generate", {"date": day})[1]["report"]
    assert "Worked on dayflow" in draft["markdown"]
    saved = call(api, "PUT", "/api/report", {"date": day, "markdown": draft["markdown"] + "\nnote", "generated": draft})[1]["report"]
    assert saved["edited"] and saved["sections"]["progress"]
    assert call(api, "GET", "/api/report", date=day)[1]["report"]["markdown"].endswith("note")

    assert "dayflow" in call(api, "POST", "/api/agent", {"question": "what did I do today"})[1]["text"]

    assert call(api, "PUT", "/api/settings", {"config": {"ai": {"provider": "evil"}}})[0] == 400
    assert call(api, "PUT", "/api/settings", {"config": {"web_port": 80}})[0] == 400
    assert call(api, "PUT", "/api/settings", {"config": {"ai": {"opencode_path": "C:/Windows/calc.exe"}}})[0] == 400
    status, _ = call(api, "PUT", "/api/settings", {
        "config": {"ui_mode": "web", "report": {"time": "18:00"},
                   "ai": {"provider": "mangso", "models": {"mangso": "gpt-x"}, "report_language": "en"}},
        "api_keys": {"mangso": "sk-test-123", "groq": "gsk-456", "bogus": "x"}})
    assert status == 200 and api.ctrl.config.ui_mode == "web" and api.ctrl.config.report.time == "18:00"
    assert api.ctrl.ai_key("mangso") == "sk-test-123" and api.ctrl.ai_key("groq") == "gsk-456"
    settings = call(api, "GET", "/api/settings")[1]
    assert settings["keys_set"]["mangso"] and settings["keys_set"]["groq"] and not settings["keys_set"]["gemini"]
    assert "sk-test-123" not in json.dumps(settings) and "bogus" not in settings["keys_set"]
    info = call(api, "GET", "/api/ai")[1]
    mangso = next(p for p in info["providers"] if p["id"] == "mangso")
    assert mangso["base_url"] == "https://ai.mangso.net/v1" and mangso["model"] == "gpt-x" and mangso["key_set"]
    assert "sk-test-123" not in json.dumps(info)
    call(api, "PUT", "/api/settings", {"config": {}, "api_keys": {"groq": ""}})  # empty string clears a key
    assert api.ctrl.ai_key("groq") == ""
    assert call(api, "POST", "/api/ai/test", {"provider": "none"})[0] == 400
    status, body = call(api, "POST", "/api/ai/test", {"provider": "gemini", "model": "x"})  # no key saved
    assert status == 502 and "API key" in body["message"]

    assert call(api, "POST", "/api/pin", {"old": "bad-pin-x", "new": "another-pin"})[0] == 403
    assert call(api, "POST", "/api/pin", {"old": PIN, "new": "another-pin"})[0] == 200
    assert call(api, "GET", "/api/nope")[0] == 404
