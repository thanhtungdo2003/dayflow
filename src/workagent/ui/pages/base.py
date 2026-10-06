from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ...app import AppController


class Page(QWidget):
    """A titled, scrollable page. Subclasses implement build() and refresh()."""

    title = ""
    scrollable = True

    def __init__(self, ctrl: AppController, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctrl = ctrl
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        body.setObjectName("PageBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title = QLabel(self.title)
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.header_actions = header
        layout.addLayout(header)
        self.build(layout)
        if self.scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(body)
            outer.addWidget(scroll)
        else:
            outer.addWidget(body)

    def build(self, layout: QVBoxLayout) -> None:
        raise NotImplementedError

    def refresh(self) -> None:
        """Reload data from the controller. Only called while the vault is unlocked."""

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self.ctrl.vault.is_unlocked:
            self.refresh()
