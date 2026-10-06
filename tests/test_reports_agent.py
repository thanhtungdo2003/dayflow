import json

from datetime import date, datetime

from workagent.agent.agent import WorkAgent, parse_day
from workagent.config import Config, ReportConfig
from workagent.models import ACTIVE, Activity, Report, Task
from workagent.reports.generator import ReportGenerator, polish_with_llm
from workagent.scheduler import Scheduler
from workagent.storage.repositories import ActivityRepository, ReportRepository, TaskRepository

DAY = "2026-10-05"
BASE = datetime(2026, 10, 5, 9, 0).timestamp()


def act(offset_min, minutes, title, app="code.exe", app_name="VS Code", project="", file="",
        tickets=None, category="development"):
    start = BASE + offset_min * 60
    return Activity(id=f"a{offset_min}", start=start, end=start + minutes * 60, kind=ACTIVE, app=app,
                    app_name=app_name, title=title, project=project, file=file, tickets=tickets or [],
                    category=category)


def sample_day():
    return [
        act(0, 90, "vault.py - dayflow - Visual Studio Code", project="dayflow", file="vault.py"),
        act(90, 30, "[PROJ-42] Login fails - Jira", app="chrome.exe", app_name="Chrome",
            tickets=["PROJ-42"]),
        act(120, 25, "sqlite3.OperationalError database is locked - Google Search", app="chrome.exe",
            app_name="Chrome", category="research"),
        act(150, 30, "sqlite3.OperationalError database is locked - Google Search", app="chrome.exe",
            app_name="Chrome", category="research"),
        act(200, 40, "Daily standup", app="ms-teams.exe", app_name="Teams", category="meeting"),
    ]


def test_report_is_evidence_based():
    tasks = [Task(id="t1", title="Ship vault", status="doing", ticket="PROJ-1"),
             Task(id="t2", title="Deploy", status="blocked", notes="waiting for VPN access", needs_support=True),
             Task(id="t3", title="Write docs", status="done", done_at=BASE + 3600)]
    report = ReportGenerator(ReportConfig(block_minutes=45)).generate(DAY, sample_day(), tasks)
    progress = [i.text for i in report.sections["progress"]]
    assert any(t.startswith("Worked on dayflow — 1h 30m") for t in progress)
    assert any(t.startswith("PROJ-42: Login fails") for t in progress)
    assert any("Meetings" in t for t in progress)
    assert "Completed task: Write docs" in progress
    assert all(i.evidence for i in report.sections["progress"] if not i.text.startswith("Completed"))
    assert any("database is locked" in i.text for i in report.sections["issues"])
    blocks = report.sections["blocks"]
    assert any("Deploy" in i.text and not i.inferred for i in blocks)
    assert any(i.inferred and "Possibly stuck" in i.text for i in blocks)  # 55 min > 45
    assert any("Deploy" in i.text for i in report.sections["support"])
    plan = [i.text for i in report.sections["plan"]]
    assert plan[0] == "Continue: Ship vault (PROJ-1)"
    assert "Follow up on PROJ-42" in plan
    md = report.markdown
    for heading in ("Progress Today", "Issues Found", "Block", "Need Support / Escalation", "Plan Tomorrow"):
        assert heading in md
    assert "Evidence: 09:00–10:30 VS Code — vault.py" in md


def test_empty_day_produces_no_invented_work():
    report = ReportGenerator(ReportConfig()).generate(DAY, [], [])
    assert all(not items for items in report.sections.values())
    assert "No activity was tracked" in report.markdown


class FakeLLM:
    name, is_local = "fake", True

    def __init__(self, reply):
        self.reply = reply

    def complete(self, system, prompt):
        return self.reply


def test_llm_polish_keeps_shape_or_falls_back():
    report = ReportGenerator(ReportConfig()).generate(DAY, sample_day(), [])
    shape = {k: [f"rewritten {i}" for i, _ in enumerate(v)] for k, v in report.sections.items()}
    polished = polish_with_llm(report, FakeLLM(json.dumps(shape)))
    assert polished.generator == "rules+llm"
    assert polished.sections["progress"][0].text == "rewritten 0"
    assert polished.sections["progress"][0].evidence  # evidence preserved

    report2 = ReportGenerator(ReportConfig()).generate(DAY, sample_day(), [])
    original = [i.text for i in report2.sections["progress"]]
    bad = polish_with_llm(report2, FakeLLM(json.dumps({"progress": ["invented extra"]})))
    assert bad.generator == "rules" and [i.text for i in bad.sections["progress"]] == original


def test_report_roundtrip_through_vault(vault):
    repo = ReportRepository(vault)
    report = ReportGenerator(ReportConfig()).generate(DAY, sample_day(), [])
    report.markdown += "\nedited by me"
    report.edited = True
    repo.save(report)
    loaded = repo.get(DAY)
    assert isinstance(loaded, Report) and loaded.edited and loaded.markdown.endswith("edited by me")
    assert loaded.sections["progress"][0].evidence[0].label


def test_repositories(vault):
    acts = ActivityRepository(vault)
    for a in sample_day():
        acts.upsert(a)
    assert [a.id for a in acts.list_day(DAY)] == [a.id for a in sample_day()]
    tasks = TaskRepository(vault)
    tasks.save(Task(id="t", title="x"))
    assert tasks.list()[0].title == "x"


def test_scheduler():
    s = Scheduler(report_time="17:30", auto_lock_idle_minutes=15)
    morning = datetime(2026, 10, 5, 9, 0)
    assert s.tick(morning, 0, unlocked=False).generate_reports == []
    assert s.tick(morning, 0, unlocked=True).generate_reports == ["2026-10-04"]
    assert s.tick(morning, 0, unlocked=True).generate_reports == []
    evening = datetime(2026, 10, 5, 17, 31)
    assert s.tick(evening, 0, unlocked=True, has_report=lambda d: False).generate_reports == ["2026-10-05"]
    s2 = Scheduler()
    assert s2.tick(evening, 0, unlocked=True, has_report=lambda d: True).generate_reports == []
    assert s.tick(evening, 16 * 60, unlocked=True).lock_vault
    assert not s.tick(evening, 16 * 60, unlocked=False).lock_vault


def _agent(acts, provider=None, allowed=False):
    return WorkAgent(load_day=lambda d: [a for a in acts if a.day == d], load_tasks=lambda: [],
                     current_activity=lambda: acts[0], generator=ReportGenerator(ReportConfig()),
                     provider=lambda: provider, llm_allowed=lambda: allowed)


def test_agent_local_intents():
    agent = _agent(sample_day())
    today = date(2026, 10, 5)
    assert "1h 30m" in agent.ask("what did I do today", today).text
    assert "dayflow" in agent.ask("hôm nay tôi làm gì", today).text
    assert "Tìm thấy" in agent.ask("find database is locked", today).text
    assert "Tìm thấy" in agent.ask("tìm database", today).text
    assert "dayflow" in agent.ask("how long on dayflow", today).text
    assert "Bị chặn" in agent.ask("any blockers today?", today).text
    assert "Kế hoạch" in agent.ask("kế hoạch ngày mai", today).text
    assert "VS Code" in agent.ask("what am I working on now", today).text
    assert parse_day("yesterday", today) == date(2026, 10, 4)


def test_agent_llm_requires_consent():
    llm = FakeLLM("You worked on dayflow.")
    today = date(2026, 10, 5)
    assert not _agent(sample_day(), llm, allowed=False).ask("summarise my mood", today).used_llm
    answer = _agent(sample_day(), llm, allowed=True).ask("summarise my mood", today)
    assert answer.used_llm and answer.shared_items > 0 and "đã chia sẻ" in answer.text


def test_config_roundtrip_and_tolerance(tmp_path):
    path = tmp_path / "c.json"
    cfg = Config()
    cfg.tracking.idle_seconds = 300
    cfg.save(path)
    assert Config.load(path).tracking.idle_seconds == 300
    path.write_text(json.dumps({"tracking": {"idle_seconds": "bad"}, "unknown": 1, "debug": True}))
    loaded = Config.load(path)
    assert loaded.tracking.idle_seconds == 180 and loaded.debug is True
    path.write_text("{not json")
    assert Config.load(path).ai.provider == "none"
    assert Config().ai.allow_chat is False and Config().privacy.browser_url_mode == "off"

