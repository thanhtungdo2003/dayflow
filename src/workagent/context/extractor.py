"""Turn (app, title, url) into semantic context: category, project, file, tickets, domain.

Pure functions over strings. Title formats are best-effort heuristics for common Windows apps;
anything unrecognised falls back to category "other" with the title as-is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..tracking.privacy import domain_of

BROWSERS = {
    "chrome.exe": "Chrome", "msedge.exe": "Edge", "firefox.exe": "Firefox", "brave.exe": "Brave",
    "opera.exe": "Opera", "vivaldi.exe": "Vivaldi", "arc.exe": "Arc", "coccoc.exe": "Cốc Cốc",
}
EDITORS = {
    "code.exe": "VS Code", "code - insiders.exe": "VS Code Insiders", "cursor.exe": "Cursor",
    "windsurf.exe": "Windsurf", "sublime_text.exe": "Sublime Text", "notepad++.exe": "Notepad++",
    "devenv.exe": "Visual Studio",
}
JETBRAINS = {
    "idea64.exe": "IntelliJ IDEA", "pycharm64.exe": "PyCharm", "webstorm64.exe": "WebStorm",
    "rider64.exe": "Rider", "goland64.exe": "GoLand", "clion64.exe": "CLion",
    "phpstorm64.exe": "PhpStorm", "datagrip64.exe": "DataGrip", "rustrover64.exe": "RustRover",
    "studio64.exe": "Android Studio",
}
TERMINALS = {
    "windowsterminal.exe": "Windows Terminal", "cmd.exe": "Command Prompt",
    "powershell.exe": "PowerShell", "pwsh.exe": "PowerShell", "conhost.exe": "Console",
    "mintty.exe": "Git Bash", "wezterm-gui.exe": "WezTerm", "alacritty.exe": "Alacritty",
}
COMMUNICATION = {
    "ms-teams.exe": "Teams", "teams.exe": "Teams", "slack.exe": "Slack", "zalo.exe": "Zalo",
    "telegram.exe": "Telegram", "discord.exe": "Discord", "outlook.exe": "Outlook",
    "olk.exe": "Outlook", "thunderbird.exe": "Thunderbird", "skype.exe": "Skype",
}
MEETINGS = {"zoom.exe": "Zoom", "webexmta.exe": "Webex"}
DOCUMENTS = {
    "winword.exe": "Word", "excel.exe": "Excel", "powerpnt.exe": "PowerPoint",
    "onenote.exe": "OneNote", "notion.exe": "Notion", "obsidian.exe": "Obsidian",
    "acrord32.exe": "Acrobat", "acrobat.exe": "Acrobat", "notepad.exe": "Notepad",
}
DESIGN = {"figma.exe": "Figma", "photoshop.exe": "Photoshop", "illustrator.exe": "Illustrator"}
DEV_TOOLS = {
    "postman.exe": "Postman", "insomnia.exe": "Insomnia", "dbeaver.exe": "DBeaver",
    "ssms.exe": "SQL Server Management Studio", "githubdesktop.exe": "GitHub Desktop",
    "sourcetree.exe": "Sourcetree", "docker desktop.exe": "Docker Desktop",
}
SELF_APPS = {"personalworkagent.exe"}

_BROWSER_SUFFIX = re.compile(
    r"\s+[-—–]\s+(?:Google Chrome|Mozilla Firefox|Firefox|Brave|Opera|Vivaldi|Arc|Cốc Cốc)\s*$"
    # Edge appends the profile name: "Title - Personal - Microsoft​ Edge"
    r"|(?:\s+and \d+ more pages?)?(?:\s+[-—–]\s+[^-—–]+)?\s+[-—–]\s+Microsoft​?\s?Edge\s*$"
)
_COUNTER_PREFIX = re.compile(r"^\(\d+\+?\)\s*")
_TICKET = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,6})\b")
_TICKET_FALSE_PREFIXES = {
    "UTF", "ISO", "SHA", "AES", "RFC", "CVE", "TLS", "SSL", "HTTP", "MP", "PEP", "COVID", "GPT",
    "WIN", "X", "ES", "ECMA", "IEC", "IEEE", "RS", "CP", "KB", "MS", "ID", "PR", "RC", "TS", "V",
}
_FILE = re.compile(r"[\w.-]+\.(?:py|js|jsx|ts|tsx|java|kt|cs|go|rs|rb|php|c|cc|cpp|h|hpp|swift|"
                   r"sql|json|ya?ml|toml|md|html|css|scss|vue|svelte|sh|ps1|xml|gradle|ipynb|"
                   r"txt|csv|docx?|xlsx?|pptx?|pdf)\b", re.IGNORECASE)
_PATH_TAIL = re.compile(r"(?:[A-Za-z]:)?[\\/](?:[^\\/:*?\"<>|\s]+[\\/])*([^\\/:*?\"<>|\s]+)[\\/]?\s*$")
_ISSUE_WORDS = re.compile(
    r"(?i)(?:\w*(?:error|exception)\b|\b(?:traceback|failed|failure|crash|bug|stack ?trace|segfault|"
    r"not working|doesn'?t work|cannot|can'?t|unable to|timeout|undefined|null ?pointer|"
    r"lỗi|không chạy|không được)\b)")
_SEARCH_SUFFIX = re.compile(r"\s+[-—–]\s+(?:Google Search|Tìm trên Google|Bing|DuckDuckGo|Search)\s*$",
                            re.IGNORECASE)
_RESEARCH_SITES = ("stackoverflow.com", "stackexchange.com", "developer.mozilla.org",
                   "learn.microsoft.com", "docs.python.org", "readthedocs", "chatgpt.com",
                   "claude.ai", "perplexity.ai")
_RESEARCH_TITLES = re.compile(r"(?i)(stack overflow|mdn web docs|documentation|\bdocs\b|"
                              r"microsoft learn|tutorial|how to)")


@dataclass
class Context:
    app_name: str
    category: str
    title: str                      # normalised title (browser suffix and counters removed)
    project: str = ""
    file: str = ""
    tickets: list[str] = field(default_factory=list)
    domain: str = ""


def friendly_app_name(app: str) -> str:
    for table in (BROWSERS, EDITORS, JETBRAINS, TERMINALS, COMMUNICATION, MEETINGS, DOCUMENTS,
                  DESIGN, DEV_TOOLS):
        if app in table:
            return table[app]
    if app in SELF_APPS:
        return "Personal Work Agent"
    name = app[:-4] if app.endswith(".exe") else app
    return name[:1].upper() + name[1:] if name else "Unknown"


def find_tickets(text: str, allowed_projects: list[str] | None = None) -> list[str]:
    allowed = {p.upper() for p in allowed_projects or []}
    found: list[str] = []
    for prefix, number in _TICKET.findall(text):
        if allowed and prefix not in allowed:
            continue
        if not allowed and (prefix in _TICKET_FALSE_PREFIXES or prefix.isdigit()):
            continue
        key = f"{prefix}-{number}"
        if key not in found:
            found.append(key)
    return found


def looks_like_issue(title: str) -> bool:
    return bool(_ISSUE_WORDS.search(title))


def normalise_title(app: str, title: str) -> str:
    title = _COUNTER_PREFIX.sub("", title.strip())
    title = title.lstrip("●•* ").strip()
    if app in BROWSERS:
        title = _BROWSER_SUFFIX.sub("", title).strip()
    return title


class ContextExtractor:
    def __init__(self, ticket_projects: list[str] | None = None,
                 project_rules: list[dict[str, str]] | None = None):
        self._ticket_projects = ticket_projects or []
        self._rules = [(r.get("match", "").lower(), r.get("project", ""))
                       for r in project_rules or [] if r.get("match") and r.get("project")]

    def extract(self, app: str, title: str, url: str = "") -> Context:
        app = app.lower()
        name = friendly_app_name(app)
        clean = normalise_title(app, title)
        ctx = Context(app_name=name, category=self._category(app, clean, url), title=clean,
                      domain=domain_of(url))
        if app in EDITORS or app in JETBRAINS:
            ctx.project, ctx.file = self._editor_context(app, clean)
        elif app in TERMINALS:
            ctx.project = self._terminal_project(clean)
        elif app in BROWSERS:
            ctx.project = self._github_repo(clean)
        if not ctx.file:
            match = _FILE.search(clean)
            ctx.file = match.group(0) if match else ""
        ctx.tickets = find_tickets(f"{clean} {url}", self._ticket_projects)
        for needle, project in self._rules:  # user rules win over heuristics
            if needle in f"{app} {clean} {url}".lower():
                ctx.project = project
                break
        return ctx

    @staticmethod
    def _category(app: str, title: str, url: str) -> str:
        if app in SELF_APPS:
            return "system"
        if app in EDITORS or app in JETBRAINS or app in TERMINALS or app in DEV_TOOLS:
            return "development"
        if app in MEETINGS:
            return "meeting"
        if app in COMMUNICATION:
            lowered = title.lower()
            if any(w in lowered for w in ("meeting", "call", "cuộc họp", "họp", "huddle", "standup", "stand-up", "sync")):
                return "meeting"
            return "communication"
        if app in DOCUMENTS:
            return "documents"
        if app in DESIGN:
            return "design"
        if app in BROWSERS:
            host = domain_of(url)
            if _SEARCH_SUFFIX.search(title) or any(s in host for s in _RESEARCH_SITES) \
                    or _RESEARCH_TITLES.search(title):
                return "research"
            if re.search(r"(?i)\b(github|gitlab|bitbucket|jira|confluence|azure devops|localhost)\b",
                         f"{title} {host}"):
                return "development"
            if re.search(r"(?i)\b(meet\.google|teams|zoom)\b", f"{title} {host}"):
                return "meeting"
            if re.search(r"(?i)\b(gmail|outlook|mail|slack|zalo|messenger)\b", f"{title} {host}"):
                return "communication"
            return "browsing"
        if app in ("explorer.exe", "taskmgr.exe", "systemsettings.exe", "applicationframehost.exe"):
            return "system"
        return "other"

    @staticmethod
    def _editor_context(app: str, title: str) -> tuple[str, str]:
        if app in JETBRAINS:
            # "project – path/file.py" (en dash) or "project [path] – file.py"
            parts = [p.strip() for p in re.split(r"\s+–\s+", title) if p.strip()]
            project = re.sub(r"\s*\[.*?\]\s*", "", parts[0]) if parts else ""
            file = parts[-1].split("/")[-1].split("\\")[-1] if len(parts) > 1 else ""
            return project, file
        # VS Code family: "file.py - project - Visual Studio Code"; Visual Studio: "Sln - Microsoft Visual Studio"
        parts = [p.strip() for p in re.split(r"\s+[-—]\s+", title) if p.strip()]
        if parts and re.search(r"(?i)visual studio|cursor|windsurf|sublime|notepad\+\+", parts[-1]):
            parts = parts[:-1]
        if app == "devenv.exe":
            return (parts[0] if parts else ""), ""
        if len(parts) >= 2:
            return parts[-1].removesuffix(" (Workspace)"), parts[0]
        if len(parts) == 1:
            return ("", parts[0]) if _FILE.fullmatch(parts[0]) else (parts[0], "")
        return "", ""

    @staticmethod
    def _terminal_project(title: str) -> str:
        # "MINGW64:/d/proj/x", "user@host: ~/proj/x", "C:\proj\x", "Administrator: C:\proj\x"
        candidate = title.split(": ", 1)[-1] if ": " in title else title
        match = _PATH_TAIL.search(candidate.replace("~", "/~"))
        if match:
            tail = match.group(1)
            if tail.lower() not in ("system32", "~", "windows", "users") and not tail.lower().endswith(".exe"):
                return tail
        return ""

    @staticmethod
    def _github_repo(title: str) -> str:
        # "owner/repo: description", "Pull Request #1 · owner/repo", "Issues · owner/repo"
        match = re.search(r"(?:^|·\s)([\w.-]+)/([\w.-]+)(?::|\s·|\s*$)", title)
        return match.group(2) if match else ""
