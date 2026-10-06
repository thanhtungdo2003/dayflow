"""Work agent: answers questions about the user's own history.

Works fully offline with intent rules over the vault. If an AI provider is configured AND
`ai.allow_chat` is on, it retrieves the relevant activities locally and sends only that
excerpt (already privacy-filtered) to the model, telling the user how much was shared.
English and Vietnamese phrasing are both understood.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from ..ai.providers import AIProvider, AIProviderError
from ..context.sessions import format_duration, summarize_day
from ..models import ACTIVE, Activity, Task
from ..reports.generator import ReportGenerator

HELP = (
    "Bạn có thể hỏi (tiếng Việt hoặc tiếng Anh):\n"
    "• hôm nay / hôm qua / 2026-10-01 tôi làm gì\n"
    "• tôi đang làm gì\n"
    "• tìm <từ khoá> — tìm trong 30 ngày gần nhất\n"
    "• bao lâu <dự án/ứng dụng/ticket>\n"
    "• các phiên làm việc hôm nay\n"
    "• hôm nay có vướng / lỗi gì\n"
    "• kế hoạch ngày mai"
)


@dataclass
class AgentAnswer:
    text: str
    used_llm: bool = False
    shared_items: int = 0


def _hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def parse_day(text: str, today: date) -> date | None:
    lowered = text.lower()
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", lowered)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None
    if "yesterday" in lowered or "hôm qua" in lowered:
        return today - timedelta(days=1)
    if "today" in lowered or "hôm nay" in lowered:
        return today
    return None


class WorkAgent:
    def __init__(self, load_day: Callable[[str], list[Activity]],
                 load_tasks: Callable[[], list[Task]],
                 current_activity: Callable[[], Activity | None],
                 generator: ReportGenerator,
                 provider: Callable[[], AIProvider | None] = lambda: None,
                 llm_allowed: Callable[[], bool] = lambda: False):
        self._load_day = load_day
        self._load_tasks = load_tasks
        self._current = current_activity
        self._generator = generator
        self._provider = provider
        self._llm_allowed = llm_allowed

    def ask(self, question: str, today: date | None = None) -> AgentAnswer:
        today = today or date.today()
        q = question.strip()
        lowered = q.lower()
        if not q or lowered in ("help", "?", "trợ giúp"):
            return AgentAnswer(HELP)

        if re.search(r"\b(now|current|currently)\b|đang làm|hiện tại", lowered):
            return AgentAnswer(self._now())
        match = re.match(r"^(?:find|search|tìm(?: kiếm)?)\s+(.+)$", lowered)
        if match:
            return AgentAnswer(self._search(match.group(1), today))
        match = re.search(r"(?:how long|how much time|time on|bao lâu)\s*(?:on|did i spend on|cho|với)?\s*(.+?)\??$", lowered)
        if match and match.group(1).strip():
            return AgentAnswer(self._time_on(match.group(1).strip(), today))

        day = parse_day(lowered, today) or today
        if re.search(r"block|stuck|issue|problem|vướng|lỗi|kẹt", lowered):
            return AgentAnswer(self._report_sections(day, ("issues", "blocks", "support")))
        if re.search(r"\bplan\b|\bnext\b|tomorrow|kế hoạch|ngày mai", lowered):
            return AgentAnswer(self._report_sections(day, ("plan",)))
        if "session" in lowered or "phiên" in lowered:
            return AgentAnswer(self._sessions(day))
        if parse_day(lowered, today) or re.search(r"what did i|summary|tóm tắt|làm gì", lowered):
            return AgentAnswer(self._day_summary(day))
        return self._llm_or_help(q, today)

    # --- local intents ----------------------------------------------------------------------

    def _now(self) -> str:
        act = self._current()
        if act is None:
            return "Hiện không có hoạt động nào đang được ghi (tạm dừng, vắng mặt hoặc vừa khởi động)."
        parts = [f"{act.app_name or act.app}"]
        if act.project:
            parts.append(f"dự án {act.project}")
        if act.file:
            parts.append(f"tệp {act.file}")
        if act.tickets:
            parts.append("ticket " + ", ".join(act.tickets))
        return f"Từ {_hm(act.start)}: " + " · ".join(parts) + (f"\n“{act.title}”" if act.title else "")

    def _day_summary(self, day: date) -> str:
        acts = self._load_day(day.isoformat())
        s = summarize_day(day.isoformat(), acts)
        if s.first_ts is None:
            return f"Không có hoạt động nào ngày {day.isoformat()}."
        lines = [f"{day.isoformat()}: {format_duration(s.active_seconds)} hoạt động, "
                 f"{_hm(s.first_ts)}–{_hm(s.last_ts)}, {len(s.sessions)} phiên."]
        if s.by_project:
            lines.append("Dự án: " + ", ".join(f"{p} {format_duration(t)}"
                                                  for p, t in list(s.by_project.items())[:5]))
        if s.by_ticket:
            lines.append("Ticket: " + ", ".join(f"{k} {format_duration(t)}"
                                                 for k, t in list(s.by_ticket.items())[:5]))
        lines.append("Ứng dụng: " + ", ".join(f"{a} {format_duration(t)}" for a, t in list(s.by_app.items())[:5]))
        return "\n".join(lines)

    def _sessions(self, day: date) -> str:
        s = summarize_day(day.isoformat(), self._load_day(day.isoformat()))
        if not s.sessions:
            return f"Không có phiên làm việc nào ngày {day.isoformat()}."
        return "\n".join(f"• {_hm(x.start)}–{_hm(x.end)} {x.label} ({format_duration(x.active_seconds)})"
                         for x in s.sessions)

    def _search(self, needle: str, today: date, days: int = 30) -> str:
        hits: list[Activity] = []
        for offset in range(days):
            day = (today - timedelta(days=offset)).isoformat()
            for a in self._load_day(day):
                hay = f"{a.title} {a.app_name} {a.project} {a.file} {a.url} {' '.join(a.tickets)}".lower()
                if a.kind == ACTIVE and needle in hay:
                    hits.append(a)
        if not hits:
            return f"Không tìm thấy hoạt động khớp “{needle}” trong {days} ngày qua."
        grouped: dict[tuple[str, str], list[Activity]] = defaultdict(list)
        for a in hits:
            grouped[(a.day, a.title or a.app_name)].append(a)
        lines = [f"Tìm thấy {len(hits)} hoạt động khớp:"]
        for (day, title), acts in sorted(grouped.items(), key=lambda kv: kv[1][0].start, reverse=True)[:15]:
            total = sum(a.duration for a in acts)
            lines.append(f"• {day} {_hm(acts[0].start)} — {title} ({format_duration(total)})")
        return "\n".join(lines)

    def _time_on(self, needle: str, today: date, days: int = 7) -> str:
        total = 0.0
        per_day: dict[str, float] = defaultdict(float)
        for offset in range(days):
            day = (today - timedelta(days=offset)).isoformat()
            for a in self._load_day(day):
                hay = f"{a.project} {a.app_name} {a.app} {' '.join(a.tickets)} {a.title}".lower()
                if a.kind == ACTIVE and needle in hay:
                    total += a.duration
                    per_day[day] += a.duration
        if not total:
            return f"Chưa ghi nhận thời gian cho “{needle}” trong {days} ngày qua."
        breakdown = ", ".join(f"{d}: {format_duration(t)}" for d, t in sorted(per_day.items(), reverse=True))
        return f"“{needle}”: {format_duration(total)} trong {days} ngày qua ({breakdown})."

    def _report_sections(self, day: date, keys: tuple[str, ...]) -> str:
        report = self._generator.generate(day.isoformat(), self._load_day(day.isoformat()), self._load_tasks())
        titles = {"issues": "Vấn đề", "blocks": "Bị chặn", "support": "Cần hỗ trợ", "plan": "Kế hoạch"}
        lines: list[str] = []
        for key in keys:
            items = report.sections.get(key, [])
            lines.append(f"{titles[key]}:")
            lines += [f"• {'(inferred) ' if i.inferred else ''}{i.text}" for i in items] or ["• không có"]
        return "\n".join(lines)

    # --- optional LLM -----------------------------------------------------------------------

    def _llm_or_help(self, question: str, today: date) -> AgentAnswer:
        provider = self._provider() if self._llm_allowed() else None
        if provider is None:
            return AgentAnswer("Tôi chỉ trả lời được bằng quy tắc cục bộ (chưa bật AI cho trợ lý).\n\n" + HELP)
        context_lines = []
        for offset in range(2):
            day = (today - timedelta(days=offset)).isoformat()
            for a in self._load_day(day):
                if a.kind == ACTIVE and a.duration >= 60:
                    context_lines.append(f"{day} {_hm(a.start)}-{_hm(a.end)} | {a.app_name} | "
                                         f"{a.project} | {a.title} | {','.join(a.tickets)}")
        context_lines = context_lines[-300:]
        tasks = [f"[{t.status}] {t.title} {t.ticket}" for t in self._load_tasks()][:50]
        system = ("You are a personal work assistant. Answer ONLY from the activity log and task "
                  "list provided. If the answer is not in them, say you don't know. Be concise. "
                  "Answer in the language of the question.")
        prompt = ("Activity log (date time | app | project | title | tickets):\n" + "\n".join(context_lines)
                  + "\n\nTasks:\n" + "\n".join(tasks) + f"\n\nQuestion: {question}")
        try:
            answer = provider.complete(system, prompt)
        except AIProviderError as exc:
            return AgentAnswer(f"Lỗi nhà cung cấp AI: {exc}")
        where = "mô hình cục bộ" if provider.is_local else "nhà cung cấp AI bên ngoài"
        return AgentAnswer(f"{answer}\n\n— đã chia sẻ {len(context_lines)} hoạt động và {len(tasks)} công việc "
                           f"với {where}.", used_llm=True, shared_items=len(context_lines) + len(tasks))
