"""Generated GUI icons and tooltip positioning helpers."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QStyle

TOOLTIP_SCREEN_MARGIN = 8
NO_ENTRY_ICON_SVG = b"""\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36">
  <circle cx="18" cy="18" r="15" fill="#FFFFFF" stroke="#16A34A" stroke-width="6"/>
  <line x1="10.8" y1="10.8" x2="25.2" y2="25.2" stroke="#16A34A" stroke-width="6" stroke-linecap="round"/>
</svg>
"""


def _fixed_size_pixmap(source: QPixmap, size: QSize) -> QPixmap:
    screen = QApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    physical_size = QSize(
        min(source.width(), max(1, round(size.width() * ratio))),
        min(source.height(), max(1, round(size.height() * ratio))),
    )
    pixmap = source.scaled(
        physical_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def _normalization_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#475569"))
    painter.drawRoundedRect(5, 22, 22, 2, 1, 1)
    painter.drawRoundedRect(5, 8, 2, 16, 1, 1)
    for x, y, height, color in (
        (10, 15, 7, "#38bdf8"),
        (15, 11, 11, "#22c55e"),
        (20, 7, 15, "#f59e0b"),
    ):
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(x, y, 4, height, 1, 1)
    painter.end()
    return QIcon(pixmap)


def _ignore_reason_icon(reason: str, size: int = 18) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(NO_ENTRY_ICON_SVG).render(painter, pixmap.rect())

    badge_size = max(10, round(size * 0.62))
    badge_rect = QRect(size - badge_size, size - badge_size, badge_size, badge_size)
    painter.setPen(QPen(QColor("#ffffff"), 1))
    painter.setBrush(QColor("#334155"))
    painter.drawEllipse(badge_rect)
    badge_font = QFont(QApplication.font())
    badge_font.setBold(True)
    badge_font.setPixelSize(max(7, round(size * 0.42)))
    painter.setFont(badge_font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, reason)
    painter.end()
    return QIcon(pixmap)


def _advanced_icon() -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont(QApplication.font())
    font.setPixelSize(50)
    painter.setFont(font)
    painter.setPen(QColor("#475569"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "⚙")
    painter.end()
    return QIcon(pixmap)


def _speaker_icon(*, enabled: bool = True) -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    speaker_color = QColor("#475569" if enabled else "#9ca3af")
    painter.setBrush(speaker_color)
    body = QPainterPath()
    body.moveTo(11, 24)
    body.lineTo(21, 24)
    body.lineTo(34, 13)
    body.lineTo(34, 43)
    body.lineTo(21, 32)
    body.lineTo(11, 32)
    body.closeSubpath()
    painter.drawPath(body)
    if enabled:
        painter.setPen(QPen(QColor("#2563eb"), 4))
        painter.drawArc(35, 19, 10, 18, -45 * 16, 90 * 16)
        painter.drawArc(38, 13, 16, 30, -45 * 16, 90 * 16)
    else:
        painter.setPen(QPen(QColor("#6b7280"), 5))
        painter.drawLine(13, 44, 48, 12)
    painter.end()
    return QIcon(pixmap)


def _record_icon(*, recording: bool = True) -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#991b1b" if recording else "#6b7280"), 2))
    painter.setBrush(QColor("#dc2626" if recording else "#9ca3af"))
    painter.drawEllipse(14, 14, 28, 28)
    painter.end()
    return QIcon(pixmap)


def _save_as_icon() -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    save_pixmap = (
        QApplication.style()
        .standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        .pixmap(pixmap.size())
    )

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, save_pixmap)

    painter.save()
    painter.translate(42, 40)
    painter.rotate(-35)
    painter.setPen(QPen(QColor("#92400e"), 1))
    painter.setBrush(QColor("#fbbf24"))
    painter.drawRoundedRect(-4, -14, 8, 24, 2, 2)
    painter.setBrush(QColor("#fef3c7"))
    tip = QPainterPath()
    tip.moveTo(-4, -14)
    tip.lineTo(0, -21)
    tip.lineTo(4, -14)
    tip.closeSubpath()
    painter.drawPath(tip)
    painter.setBrush(QColor("#475569"))
    painter.drawRoundedRect(-4, 9, 8, 5, 1, 1)
    painter.restore()

    painter.end()
    return QIcon(pixmap)


def _save_measurement_icon() -> QIcon:
    pixmap = QPixmap(56, 56)
    pixmap.fill(Qt.GlobalColor.transparent)

    save_pixmap = (
        QApplication.style()
        .standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        .pixmap(pixmap.size())
    )

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, save_pixmap)

    painter.setPen(QPen(QColor("#334155"), 1))
    painter.setBrush(QColor("#f8fafc"))
    painter.drawRoundedRect(29, 27, 22, 22, 4, 4)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#38bdf8"))
    painter.drawRoundedRect(34, 38, 3, 7, 1, 1)
    painter.setBrush(QColor("#22c55e"))
    painter.drawRoundedRect(39, 34, 3, 11, 1, 1)
    painter.setBrush(QColor("#f59e0b"))
    painter.drawRoundedRect(44, 31, 3, 14, 1, 1)
    painter.setPen(QPen(QColor("#475569"), 1))
    painter.drawLine(33, 45, 48, 45)
    painter.end()
    return QIcon(pixmap)


def _tooltip_size_hint(text: str) -> QSize:
    metrics = QFontMetrics(QApplication.font())
    lines = text.splitlines() or [text]
    width = max((metrics.horizontalAdvance(line) for line in lines), default=0)
    height = metrics.lineSpacing() * max(1, len(lines))
    return QSize(width + 18, height + 12)


def _visible_tooltip_position(anchor: QPoint, tooltip_size: QSize, available: QRect) -> QPoint:
    left = available.left() + TOOLTIP_SCREEN_MARGIN
    top = available.top() + TOOLTIP_SCREEN_MARGIN
    right = available.right() - TOOLTIP_SCREEN_MARGIN
    bottom = available.bottom() - TOOLTIP_SCREEN_MARGIN

    x = anchor.x()
    y = anchor.y()
    if x + tooltip_size.width() > right:
        x = anchor.x() - tooltip_size.width()
    if y + tooltip_size.height() > bottom:
        y = anchor.y() - tooltip_size.height()

    x = max(left, min(x, right - tooltip_size.width()))
    y = max(top, min(y, bottom - tooltip_size.height()))
    return QPoint(x, y)
