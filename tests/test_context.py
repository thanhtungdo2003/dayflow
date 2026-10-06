from workagent.context.extractor import ContextExtractor, find_tickets
from workagent.context.sessions import build_sessions, format_duration, summarize_day
from workagent.models import ACTIVE, AWAY, Activity

X = ContextExtractor()


def test_vscode_title():
    ctx = X.extract("code.exe", "● vault.py - dayflow - Visual Studio Code")
    assert (ctx.category, ctx.project, ctx.file, ctx.app_name) == ("development", "dayflow", "vault.py", "VS Code")


def test_jetbrains_title():
    ctx = X.extract("pycharm64.exe", "backend – services/auth.py")
    assert ctx.project == "backend" and ctx.file == "auth.py"


def test_terminal_titles():
    assert X.extract("mintty.exe", "MINGW64:/d/MyProjects/dayflow").project == "dayflow"
    assert X.extract("windowsterminal.exe", "Administrator: C:\\work\\api").project == "api"
    assert X.extract("powershell.exe", "Windows PowerShell").project == ""


def test_browser_titles():
    ctx = X.extract("chrome.exe", "(3) [PROJ-42] Login fails on Safari - Jira - Google Chrome")
    assert ctx.title == "[PROJ-42] Login fails on Safari - Jira"
    assert ctx.tickets == ["PROJ-42"] and ctx.category == "development"
    gh = X.extract("msedge.exe", "Fix vault lock · Pull Request #12 · acme/dayflow - Personal - Microsoft\u200b Edge")
    assert gh.project == "dayflow"
    search = X.extract("chrome.exe", "sqlite database is locked python - Google Search - Google Chrome")
    assert search.category == "research"


def test_ticket_false_positives():
    assert find_tickets("UTF-8 SHA-256 AES-256 ISO-8601 COVID-19 PROJ-7") == ["PROJ-7"]
    assert find_tickets("ABC-1 PROJ-2", allowed_projects=["proj"]) == ["PROJ-2"]


def test_project_rules_override():
    x = ContextExtractor(project_rules=[{"match": "acme", "project": "ACME Portal"}])
    assert x.extract("chrome.exe", "acme admin - Google Chrome").project == "ACME Portal"


def _a(start, end, kind=ACTIVE, project="p", tickets=None):
    return Activity(id=f"{start}", start=start, end=end, kind=kind, app="code.exe", app_name="VS Code",
                    project=project, tickets=tickets or [], category="development")


def test_sessions_split_on_long_away():
    acts = [_a(0, 600), _a(650, 1200), _a(1200, 2400, kind=AWAY), _a(2400, 3000, project="q")]
    sessions = build_sessions(acts, break_seconds=300)
    assert len(sessions) == 2
    assert sessions[0].active_seconds == 1150 and sessions[0].project == "p"
    assert sessions[1].project == "q"


def test_day_summary():
    acts = [_a(0, 600, tickets=["PROJ-1"]), _a(600, 900, kind=AWAY), _a(900, 1500, project="q")]
    s = summarize_day("d", acts)
    assert s.active_seconds == 1200 and s.away_seconds == 300
    assert s.by_project == {"p": 600, "q": 600} and s.by_ticket == {"PROJ-1": 600}


def test_format_duration():
    assert format_duration(30) == "30s"
    assert format_duration(90) == "2m"
    assert format_duration(3720) == "1h 02m"
