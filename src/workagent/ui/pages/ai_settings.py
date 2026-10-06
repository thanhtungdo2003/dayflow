"""AI provider settings box for the desktop UI: provider, model (with live list), per-provider
API key, OpenCode CLI path, connection test and report options."""

from __future__ import annotations

import copy
import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget,
)

from ...ai.opencode import find_opencode
from ...ai.providers import PROVIDERS, AIProviderError, is_local_url, model_for, spec_for
from ...config import AIConfig
from .. import theme


def _row(*widgets) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for i, x in enumerate(widgets):
        h.addWidget(x, 1 if i == 0 else 0)
    return w


class AiSettingsBox(QGroupBox):
    _done = Signal(str, object)  # ("models"|"test", result or AIProviderError) from a worker thread

    def __init__(self, ctrl, parent: QWidget | None = None):
        super().__init__("AI (tuỳ chọn)", parent)
        self.ctrl = ctrl
        self._cfg = AIConfig()
        self._pending: dict[str, str] = {}
        self._live_models: dict[str, list[str]] = {}
        self._provider_id = "none"
        form = QFormLayout(self)
        self._form = form

        self._provider = QComboBox()
        for spec in PROVIDERS.values():
            self._provider.addItem(spec.label, spec.id)
        self._provider.currentIndexChanged.connect(self._on_provider)
        self._kind = QLabel("")
        self._key_link = QLabel("")
        self._key_link.setOpenExternalLinks(True)
        self._base_url = QLineEdit()
        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setMinimumWidth(260)
        self._load_btn = QPushButton("Tải danh sách")
        self._load_btn.clicked.connect(self._load_models)
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._clear_key = QPushButton("Xoá key")
        self._clear_key.setObjectName("Danger")
        self._clear_key.clicked.connect(self._on_clear_key)
        self._oc_status = QLabel("")
        self._oc_path = QLineEdit()
        self._oc_note = QLabel("Model của OpenCode (kể cả Big Pickle miễn phí) chạy trên máy chủ OpenCode, không phải trên "
                               "máy bạn. Mỗi lần gọi chạy trong thư mục trống; nếu agent định dùng công cụ, kết quả bị huỷ.")
        self._oc_note.setWordWrap(True)
        self._oc_note.setStyleSheet(f"color: {theme.WARN};")
        self._test_btn = QPushButton("Kiểm tra kết nối")
        self._test_btn.clicked.connect(self._test)
        self._test_result = QLabel("")
        self._test_result.setWordWrap(True)
        self._mode = QComboBox()
        self._mode.addItem("Tổng hợp từ lịch sử hoạt động", "compose")
        self._mode.addItem("Chỉ viết lại câu chữ của bản nháp", "polish")
        self._lang = QComboBox()
        self._lang.addItem("Tiếng Việt", "vi")
        self._lang.addItem("English", "en")
        self._allow_reports = QCheckBox("Cho phép gửi lịch sử hoạt động để AI viết báo cáo")
        self._allow_chat = QCheckBox("Cho phép gửi trích đoạn khi hỏi trợ lý")

        form.addRow("Nhà cung cấp", self._provider)
        form.addRow("", _row(self._kind, self._key_link))
        form.addRow("Base URL", self._base_url)
        form.addRow("Model", _row(self._model, self._load_btn))
        form.addRow("API key", _row(self._key, self._clear_key))
        form.addRow("OpenCode CLI", _row(self._oc_path, self._oc_status))
        form.addRow("", self._oc_note)
        form.addRow("Kiểm tra", _row(self._test_result, self._test_btn))
        form.addRow("AI cho báo cáo", self._mode)
        form.addRow("Ngôn ngữ báo cáo AI", self._lang)
        form.addRow(self._allow_reports)
        form.addRow(self._allow_chat)
        self._done.connect(self._on_done)

    # --- load / apply ---------------------------------------------------------------------

    def load(self, ai: AIConfig) -> None:
        self._cfg = copy.deepcopy(ai)
        self._pending = {}
        self._provider_id = ai.provider if ai.provider in PROVIDERS else "none"
        self._mode.setCurrentIndex(max(0, self._mode.findData(ai.report_mode)))
        self._lang.setCurrentIndex(max(0, self._lang.findData(ai.report_language)))
        self._allow_reports.setChecked(ai.allow_reports)
        self._allow_chat.setChecked(ai.allow_chat)
        self._provider.blockSignals(True)
        self._provider.setCurrentIndex(max(0, self._provider.findData(self._provider_id)))
        self._provider.blockSignals(False)
        self._show_provider()

    def apply(self, ai: AIConfig) -> dict[str, str]:
        """Write the edited values into `ai`; returns API keys to store ({} if none changed)."""
        self._capture()
        ai.provider = self._provider_id
        ai.models = dict(self._cfg.models)
        ai.model = ai.models.get(ai.provider, "")
        ai.base_url = self._cfg.base_url
        ai.opencode_path = self._cfg.opencode_path
        ai.report_mode = self._mode.currentData()
        ai.report_language = self._lang.currentData()
        ai.allow_reports = self._allow_reports.isChecked()
        ai.allow_chat = self._allow_chat.isChecked()
        return dict(self._pending)

    def sends_to_cloud(self, ai: AIConfig) -> bool:
        spec = spec_for(ai.provider)
        if spec.kind == "none":
            return False
        local = is_local_url(ai.base_url or spec.base_url) if spec.url_editable else spec.local
        return not local and (ai.allow_chat or ai.allow_reports)

    # --- provider switching ---------------------------------------------------------------

    def _capture(self) -> None:
        """Store what is typed for the currently shown provider."""
        spec = spec_for(self._provider_id)
        model = self._model.currentText().strip()
        if model and spec.kind != "none":
            self._cfg.models[spec.id] = model
        if spec.url_editable:
            self._cfg.base_url = self._base_url.text().strip()
        if spec.kind == "opencode":
            self._cfg.opencode_path = self._oc_path.text().strip()
        if spec.needs_key and self._key.text():
            self._pending[spec.id] = self._key.text()

    def _on_provider(self) -> None:
        self._capture()
        self._provider_id = self._provider.currentData()
        self._show_provider()

    def _show_provider(self) -> None:
        spec = spec_for(self._provider_id)
        on = spec.kind != "none"
        local = (is_local_url(self._cfg.base_url or spec.base_url) if spec.url_editable else spec.local)
        if not on:
            self._kind.setText("Tắt — không gửi dữ liệu nào")
        elif local:
            self._kind.setText("Chạy trên máy này — dữ liệu không rời máy")
        else:
            self._kind.setText("Dịch vụ đám mây — dữ liệu được gửi đi khi bạn cho phép bên dưới")
        self._kind.setStyleSheet(f"color: {theme.GOOD if (not on or local) else theme.WARN}; font-weight: 600;")
        self._key_link.setText(f'<a style="color:{theme.ACCENT_DARK}" href="{spec.key_url}">Lấy API key ↗</a>'
                               if spec.key_url else "")
        self._base_url.setText(self._cfg.base_url or spec.base_url)
        self._base_url.setPlaceholderText(spec.base_url)
        self._model.clear()
        current = model_for(self._cfg, spec.id) if on else ""
        options = list(dict.fromkeys([*self._live_models.get(spec.id, []), *spec.models, current]))
        self._model.addItems([m for m in options if m])
        self._model.setCurrentText(current)
        self._key.clear()
        saved = self.ctrl.ai_keys_set().get(spec.id, False)
        pending = self._pending.get(spec.id)
        if pending == "":
            self._key.setPlaceholderText("Key sẽ bị xoá khi lưu")
        else:
            self._key.setText(pending or "")
            self._key.setPlaceholderText("●●●●●● đã lưu (mã hoá) — nhập để thay" if saved else "Dán API key")
        self._clear_key.setVisible(saved and pending != "")
        exe = find_opencode(self._cfg.opencode_path) if spec.kind == "opencode" else ""
        self._oc_path.setText(self._cfg.opencode_path)
        self._oc_path.setPlaceholderText(exe or "Tự phát hiện — hoặc nhập đường dẫn opencode.exe")
        self._oc_status.setText("✓ Đã tìm thấy" if exe else "✗ Chưa tìm thấy")
        self._oc_status.setStyleSheet(f"color: {theme.GOOD if exe else theme.CRITICAL}; font-weight: 600;")
        self._test_result.setText("")
        f = self._form
        f.setRowVisible(1, on)
        f.setRowVisible(2, spec.url_editable)
        f.setRowVisible(3, on)
        f.setRowVisible(4, on and spec.needs_key)
        f.setRowVisible(5, spec.kind == "opencode")
        f.setRowVisible(6, spec.kind == "opencode")
        for row in range(7, 12):
            f.setRowVisible(row, on)

    def _on_clear_key(self) -> None:
        self._pending[self._provider_id] = ""
        self._show_provider()

    # --- background actions ---------------------------------------------------------------

    def _call_args(self) -> tuple[str, str | None, str | None]:
        spec = spec_for(self._provider_id)
        url = self._base_url.text().strip() if spec.url_editable else None
        key = self._key.text().strip() or None
        return spec.id, url, key

    def _load_models(self) -> None:
        provider, url, key = self._call_args()
        self._load_btn.setEnabled(False)
        threading.Thread(target=self._work, daemon=True, args=(
            "models", lambda: (provider, self.ctrl.ai_list_models(provider, url, key)))).start()

    def _test(self) -> None:
        provider, url, key = self._call_args()
        model = self._model.currentText().strip()
        self._test_btn.setEnabled(False)
        self._test_result.setStyleSheet(f"color: {theme.TEXT_2};")
        self._test_result.setText("Đang kiểm tra…" + (" (OpenCode có thể mất ~1 phút)" if provider == "opencode" else ""))
        threading.Thread(target=self._work, daemon=True, args=(
            "test", lambda: self.ctrl.ai_test(provider, model, url, key))).start()

    def _work(self, kind: str, fn) -> None:
        try:
            self._done.emit(kind, fn())
        except AIProviderError as exc:
            self._done.emit(kind, exc)
        except Exception as exc:  # noqa: BLE001 - surface anything to the user, never crash the UI
            self._done.emit(kind, AIProviderError(f"lỗi: {type(exc).__name__}"))

    def _on_done(self, kind: str, result) -> None:
        if kind == "models":
            self._load_btn.setEnabled(True)
            if isinstance(result, AIProviderError):
                self._test_result.setStyleSheet(f"color: {theme.CRITICAL};")
                self._test_result.setText(f"Không tải được danh sách: {result}")
                return
            provider, models = result
            self._live_models[provider] = models
            if provider == self._provider_id:
                self._capture()
                self._show_provider()
                self._test_result.setStyleSheet(f"color: {theme.GOOD};")
                self._test_result.setText(f"Tìm thấy {len(models)} model")
        else:
            self._test_btn.setEnabled(True)
            if isinstance(result, AIProviderError):
                self._test_result.setStyleSheet(f"color: {theme.CRITICAL};")
                self._test_result.setText(f"✗ {result}")
            else:
                reply, seconds = result
                self._test_result.setStyleSheet(f"color: {theme.GOOD};")
                self._test_result.setText(f"✓ Kết nối được · {seconds:.1f}s")
                self._test_result.setToolTip(reply)
