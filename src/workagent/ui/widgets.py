"""Small reusable widgets: stat card, day timeline strip, category bars, icons."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from ..context.sessions import format_duration
from ..models import ACTIVE, AWAY, LOCKED, PRIVATE, Activity
from . import theme


class StatCard(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self._value = QLabel("—")
        self._value.setObjectName("CardValue")
        self._label = QLabel(label)
        self._label.setObjectName("CardLabel")
        layout.addWidget(self._label)
        layout.addWidget(self._value)

    def set_value(self, value: str, tooltip: str = "") -> None:
        self._value.setText(value)
        self.setToolTip(tooltip)


def _activity_category(a: Activity) -> str:
    if a.kind == PRIVATE:
        return "private"
    return theme.category_key("other" if a.category == "system" else a.category)


class TimelineStrip(QWidget):
    """One day as a horizontal strip; hover shows the activity under the cursor."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._acts: list[Activity] = []
        self._t0 = 0.0
        self._t1 = 1.0

    def set_activities(self, activities: list[Activity], day_start: float) -> None:
        self._acts = [a for a in activities if a.duration > 0]
        work = [a for a in self._acts if a.kind in (ACTIVE, PRIVATE)]
        if work:
            # Zoom to the worked hours, rounded out to whole hours.
            first = min(a.start for a in work)
            last = max(a.end for a in work)
            self._t0 = max(day_start, first - (first - day_start) % 3600)
            self._t1 = min(day_start + 86400, last + 3600 - (last - day_start) % 3600)
        else:
            self._t0, self._t1 = day_start + 8 * 3600, day_start + 18 * 3600
        self.update()

    def _bar_rect(self) -> QRectF:
        return QRectF(8, 8, max(1, self.width() - 16), 28)

    def _x(self, ts: float, rect: QRectF) -> float:
        return rect.left() + (ts - self._t0) / max(1.0, self._t1 - self._t0) * rect.width()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._bar_rect()
        track = QPainterPath()
        track.addRoundedRect(rect, 4, 4)
        p.fillPath(track, QColor(theme.AWAY_COLOR))
        p.save()
        p.setClipPath(track)
        for a in self._acts:
            if a.kind in (AWAY, LOCKED):
                continue
            x0, x1 = self._x(a.start, rect), self._x(a.end, rect)
            if x1 - x0 < 0.5:
                x1 = x0 + 0.5
            p.fillRect(QRectF(x0, rect.top(), x1 - x0, rect.height()),
                       QColor(theme.CATEGORY_COLORS[_activity_category(a)]))
        p.restore()
        # hour ticks
        p.setPen(QPen(QColor(theme.TEXT_3)))
        font = QFont(self.font())
        font.setPointSizeF(8)
        p.setFont(font)
        hours = int((self._t1 - self._t0) // 3600)
        step = 1 if hours <= 12 else 2
        for i in range(0, hours + 1, step):
            ts = self._t0 + i * 3600
            x = self._x(ts, rect)
            p.drawLine(QPointF(x, rect.bottom() + 2), QPointF(x, rect.bottom() + 6))
            label = datetime.fromtimestamp(ts).strftime("%H:%M")
            left = min(max(0.0, x - 20), self.width() - 40.0)
            p.drawText(QRectF(left, rect.bottom() + 6, 40, 16), Qt.AlignmentFlag.AlignCenter, label)
        p.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        rect = self._bar_rect()
        pos = event.position()
        if not rect.adjusted(0, -4, 0, 4).contains(pos):
            QToolTip.hideText()
            return
        ts = self._t0 + (pos.x() - rect.left()) / rect.width() * (self._t1 - self._t0)
        hit = next((a for a in self._acts if a.start <= ts <= a.end and a.kind not in (AWAY, LOCKED)), None)
        if hit is None:
            hit = next((a for a in self._acts if a.start <= ts <= a.end), None)
        if hit is None:
            QToolTip.hideText()
            return
        span = f"{datetime.fromtimestamp(hit.start):%H:%M}–{datetime.fromtimestamp(hit.end):%H:%M}"
        if hit.kind in (AWAY, LOCKED):
            text = f"{span} · {'Vắng mặt' if hit.kind == AWAY else 'Đã khoá'} ({format_duration(hit.duration)})"
        else:
            cat = theme.CATEGORY_LABELS[_activity_category(hit)]
            detail = hit.title or "(ẩn chi tiết)"
            text = f"{span} · {format_duration(hit.duration)}\n{hit.app_name or hit.app} — {cat}\n{detail}"
        QToolTip.showText(event.globalPosition().toPoint(), text, self)


class CategoryBars(QWidget):
    """Horizontal bars of time per category, each labelled with name and duration."""

    ROW = 26

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: list[tuple[str, float]] = []
        self.setMinimumHeight(self.ROW)

    def set_data(self, by_category: dict[str, float]) -> None:
        merged: dict[str, float] = {}
        for cat, secs in by_category.items():
            key = "other" if cat == "system" else theme.category_key(cat)
            merged[key] = merged.get(key, 0.0) + secs
        self._rows = sorted(((k, v) for k, v in merged.items() if v >= 30), key=lambda kv: -kv[1])
        self.setMinimumHeight(max(self.ROW, len(self._rows) * self.ROW))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(300, max(self.ROW, len(self._rows) * self.ROW))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._rows:
            p.setPen(QColor(theme.TEXT_2))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "Chưa có hoạt động nào.")
            p.end()
            return
        label_w, value_w = 120, 70
        bar_w = max(10, self.width() - label_w - value_w - 8)
        top = max(v for _, v in self._rows)
        for i, (cat, secs) in enumerate(self._rows):
            y = i * self.ROW
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(0, y, label_w, self.ROW), Qt.AlignmentFlag.AlignVCenter,
                       theme.CATEGORY_LABELS[cat])
            w = max(4.0, bar_w * secs / top)
            path = QPainterPath()
            path.addRoundedRect(QRectF(label_w, y + 7, w, self.ROW - 14), 4, 4)
            p.fillPath(path, QBrush(QColor(theme.CATEGORY_COLORS[cat])))
            p.setPen(QColor(theme.TEXT_2))
            p.drawText(QRectF(label_w + w + 8, y, value_w, self.ROW), Qt.AlignmentFlag.AlignVCenter,
                       format_duration(secs))
        p.end()


def state_icon(color: str, locked: bool = False, size: int = 64) -> QIcon:
    """Tray/app icon: a rounded tile with a timeline glyph, plus a lock badge when locked."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)
    p.fillPath(tile, QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    s = size / 64
    for x, w, y in ((12, 22, 18), (20, 30, 29), (14, 18, 40)):
        p.drawRoundedRect(QRectF(x * s, y * s, w * s, 7 * s), 3 * s, 3 * s)
    if locked:
        p.setBrush(QColor(theme.TEXT))
        p.drawRoundedRect(QRectF(36 * s, 38 * s, 22 * s, 20 * s), 4 * s, 4 * s)
        pen = QPen(QColor(theme.TEXT), 4 * s)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(40 * s, 28 * s, 14 * s, 18 * s), 0, 180 * 16)
    p.end()
    return QIcon(pix)
