from __future__ import annotations

import html

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout

from ...agent.agent import HELP, AgentAnswer
from .base import Page


class ChatPage(Page):
    title = "Trợ lý"
    scrollable = False

    def build(self, layout: QVBoxLayout) -> None:
        self._mode = QLabel("")
        self._mode.setObjectName("Hint")
        self._mode.setWordWrap(True)
        layout.addWidget(self._mode)
        self._log = QTextBrowser()
        self._log.setOpenExternalLinks(False)
        layout.addWidget(self._log, 1)
        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Hỏi về công việc — vd: “hôm qua tôi làm gì?”, “tìm login bug”")
        self._input.returnPressed.connect(self._send)
        self._send_btn = QPushButton("Gửi")
        self._send_btn.setObjectName("Primary")
        self._send_btn.clicked.connect(self._send)
        row.addWidget(self._input, 1)
        row.addWidget(self._send_btn)
        layout.addLayout(row)
        self._append("Trợ lý", HELP)
        self.ctrl.agent_answer.connect(self._on_answer)

    def refresh(self) -> None:
        ai = self.ctrl.config.ai
        if ai.provider == "none" or not ai.allow_chat:
            self._mode.setText("Chỉ chạy cục bộ — câu trả lời được tính từ lịch sử đã mã hoá của bạn. Không dữ liệu nào rời khỏi máy.")
        else:
            self._mode.setText(f"Đã bật AI ({ai.provider}). Câu hỏi mà quy tắc cục bộ không trả lời được sẽ được gửi "
                               "kèm một đoạn nhật ký hoạt động liên quan; mỗi câu trả lời ghi rõ đã chia sẻ bao nhiêu.")
        self._input.setFocus()

    def _append(self, who: str, text: str) -> None:
        body = html.escape(text).replace("\n", "<br>")
        color = "#2a78d6" if who == "Bạn" else "#52514e"
        self._log.append(f"<p><b style='color:{color}'>{who}</b><br>{body}</p>")

    def _send(self) -> None:
        question = self._input.text().strip()
        if not question:
            return
        self._input.clear()
        self._append("Bạn", question)
        self._send_btn.setEnabled(False)
        self.ctrl.ask_agent_async(question)

    def _on_answer(self, answer: AgentAnswer) -> None:
        self._send_btn.setEnabled(True)
        self._append("Trợ lý", answer.text)
