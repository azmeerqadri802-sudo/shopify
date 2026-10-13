# -*- coding: utf-8 -*-
"""Premium responsive glass UI layer for OmniStore AI Manager V3.1.

The module decorates the existing omnistore.ui application at startup. Its
dashboard controls continue to call the existing backend methods, while the
camera panel is explicitly a non-camera, non-recording visual simulation.
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

import pyqtgraph as pg
from PyQt6.QtCore import QThread, QTimer, Qt, QSize, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QDialog, QSizePolicy,
    QTableWidget, QVBoxLayout, QWidget,
)


CYAN = "#00D2FF"
VIOLET = "#8A2BE2"
PANEL = "#0B1423"
TEXT = "#E9F4FF"
MUTED = "#8DA5BB"

PREMIUM_QSS = """
QWidget { color: #E9F4FF; font-family: 'Segoe UI'; font-size: 10pt; }
QMainWindow, QDialog { background: #050A13; }
QFrame#MainSurface { background: #07101D; border: 1px solid #1A526C; border-radius: 16px; }
QFrame#GlassCard { background: rgba(13, 25, 42, 238); border: 1px solid rgba(61, 123, 157, 150); border-radius: 15px; }
QFrame#SubCard { background: rgba(9, 19, 33, 230); border: 1px solid rgba(99, 75, 157, 135); border-radius: 12px; }
QFrame#TopBar { background: rgba(5, 11, 21, 248); border: 0; border-bottom: 1px solid #153A50; }
QLabel#Brand { color: #F1FAFF; font-size: 14pt; font-weight: 700; letter-spacing: 1px; }
QLabel#SectionTitle { color: #DFF7FF; font-size: 10pt; font-weight: 700; }
QLabel#Muted { color: #8DA5BB; }
QLabel#Accent { color: #00D2FF; font-weight: 700; }
QLabel#StatusGood { color: #61F2BF; font-size: 9pt; font-weight: 700; }
QLabel#StatusSync { color: #C4A3FF; font-size: 9pt; font-weight: 700; }
QPushButton { background: #101F31; color: #DDF7FF; border: 1px solid #2B536B; border-radius: 9px; padding: 8px 12px; }
QPushButton:hover { background: #153149; border-color: #00D2FF; color: white; }
QPushButton#Primary { background: #063B50; border: 1px solid #00D2FF; color: #EAFBFF; font-weight: 700; }
QPushButton#Primary:hover { background: #07526A; }
QPushButton#Danger:hover { background: #572B3C; border-color: #FF6B83; }
QPushButton#Mic { background: #19132C; border: 1px solid #A66BFF; border-radius: 22px; min-width: 42px; min-height: 42px; font-size: 15pt; }
QPushButton#Mic:hover { background: #2B1C48; border-color: #00D2FF; }
QLineEdit, QPlainTextEdit, QTableWidget { background: #07111E; color: #DDF5FF; border: 1px solid #23475E; border-radius: 9px; padding: 8px; selection-background-color: #145A74; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #00D2FF; }
QPlainTextEdit { font-family: Consolas, 'Cascadia Mono'; font-size: 9pt; }
QTableWidget { gridline-color: #1D3042; alternate-background-color: #0A1726; }
QHeaderView::section { background: #102236; color: #90CFE2; border: 0; padding: 7px; }
QProgressBar { background: #101B2B; border: 0; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #00D2FF; border-radius: 4px; }
QTabWidget::pane { background: rgba(10, 20, 34, 245); border: 1px solid #31536C; border-radius: 10px; }
QTabBar::tab { background: #0C1928; color: #9FB4C9; padding: 10px 13px; margin: 2px; border-radius: 7px; }
QTabBar::tab:selected { background: #17334A; color: #E4FAFF; border: 1px solid #00A7CC; }
QCheckBox { spacing: 9px; color: #C7D8E8; }
QCheckBox::indicator { width: 36px; height: 19px; border-radius: 9px; background: #28384A; border: 1px solid #526A80; }
QCheckBox::indicator:checked { background: #087A8A; border-color: #00D2FF; }
QScrollBar:vertical { background: #08121E; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #28516A; min-height: 24px; border-radius: 5px; }
"""


def add_glow(widget: QWidget, color: str = CYAN, blur: int = 22) -> None:
    """Add a modest Qt shadow glow to a card or key control."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    effect.setColor(QColor(color))
    widget.setGraphicsEffect(effect)


class WindowTitleBar(QFrame):
    """Compact frameless title bar with responsive maximize/restore controls."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self._drag_offset = None
        self.setObjectName("TopBar")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 8, 6)
        brand = QLabel("◈  OMNICHANNEL AI MANAGER")
        brand.setObjectName("Brand")
        row.addWidget(brand)
        subtitle = QLabel("V3.1  ·  COMMERCE CONTROL CENTER")
        subtitle.setObjectName("Muted")
        row.addWidget(subtitle, 1)
        for label, action, object_name in (
            ("—", window.showMinimized, ""),
            ("□", self.toggle_window_state, ""),
            ("×", window.close, "Danger"),
        ):
            button = QPushButton(label)
            if object_name:
                button.setObjectName(object_name)
            button.setToolTip("Close" if label == "×" else "Minimize" if label == "—" else "Toggle maximize")
            button.clicked.connect(action)
            row.addWidget(button)

    def toggle_window_state(self) -> None:
        if self.window.isMaximized() or self.window.isFullScreen():
            self.window.showNormal()
            screen = self.window.screen()
            if screen:
                area = screen.availableGeometry()
                width, height = int(area.width() * 0.86), int(area.height() * 0.84)
                self.window.resize(width, height)
                self.window.move(area.center() - self.window.rect().center())
        else:
            self.window.showMaximized()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.window.isMaximized():
            self._drag_offset = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: Any) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class GlowingOrb(QWidget):
    """Lightweight timer-driven AI orb; painting stays on Qt's UI thread."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(110, 110)
        self._phase = 0.0
        self._thinking = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(42)

    def sizeHint(self) -> QSize:
        return QSize(230, 230)

    def set_thinking(self, active: bool) -> None:
        self._thinking = active

    def _tick(self) -> None:
        self._phase = (self._phase + (0.10 if self._thinking else 0.045)) % (2 * math.pi)
        self.update()

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = max(1, min(self.width(), self.height()) - 12)
        rect = self.rect().adjusted((self.width() - side) // 2, (self.height() - side) // 2,
                                    -(self.width() - side) // 2, -(self.height() - side) // 2)
        cx, cy = rect.center().x(), rect.center().y()
        radius = side * 0.46
        pulse = (math.sin(self._phase) + 1.0) * 0.5
        painter.setPen(Qt.PenStyle.NoPen)
        aura = QRadialGradient(cx, cy, radius)
        aura.setColorAt(0.0, QColor(0, 210, 255, 65 + int(45 * pulse)))
        aura.setColorAt(0.48, QColor(74, 69, 208, 42))
        aura.setColorAt(1.0, QColor(6, 14, 30, 0))
        painter.setBrush(aura)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
        for ring in range(4):
            offset = ((self._phase * (1.3 + ring * .14) + ring * .9) % (2 * math.pi))
            size = radius * (0.48 + 0.095 * ring + 0.018 * math.sin(offset))
            color = QColor(0, 210, 255, max(34, 155 - ring * 27)) if ring % 2 == 0 else QColor(151, 79, 255, 145 - ring * 22)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(color, max(1.1, side * 0.008)))
            painter.drawEllipse(QRectF(cx - size, cy - size, size * 2, size * 2))
        core = QRadialGradient(cx - radius * .10, cy - radius * .13, radius * .62)
        core.setColorAt(0, QColor(38, 75, 116, 230))
        core.setColorAt(.56, QColor(10, 23, 46, 245))
        core.setColorAt(1, QColor(14, 18, 44, 248))
        painter.setBrush(core)
        painter.setPen(QPen(QColor(52, 211, 255, 220), max(1.2, side * .009)))
        core_r = radius * .39
        painter.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))
        painter.setPen(QColor(235, 251, 255))
        painter.setFont(QFont("Segoe UI", max(16, int(side * .16)), QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "AI")


class VisionSimulationWorker(QThread):
    """Generates synthetic landmarks; never opens a camera or records video."""

    frame_ready = pyqtSignal(QImage, str)

    def run(self) -> None:
        index = 0
        while not self.isInterruptionRequested():
            image = QImage(640, 320, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor("#071321"))
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            gradient = QLinearGradient(0, 0, 640, 320)
            gradient.setColorAt(0, QColor("#091729"))
            gradient.setColorAt(1, QColor("#15102C"))
            painter.fillRect(image.rect(), gradient)
            painter.setPen(QPen(QColor(35, 101, 130, 75), 1))
            for x in range(0, 640, 32):
                painter.drawLine(x, 0, x, 320)
            for y in range(0, 320, 32):
                painter.drawLine(0, y, 640, y)
            sway = math.sin(index / 13.0) * 18
            palm = (325 + sway, 173 + math.sin(index / 17.0) * 10)
            fingers = [
                [(275 + sway, 160), (257 + sway, 123), (250 + sway, 83)],
                [(302 + sway, 150), (297 + sway, 101), (298 + sway, 57)],
                [(330 + sway, 145), (334 + sway, 93), (340 + sway, 51)],
                [(355 + sway, 154), (372 + sway, 110), (388 + sway, 76)],
                [(300 + sway, 183), (267 + sway, 205), (238 + sway, 198)],
            ]
            joints: list[tuple[float, float]] = [palm]
            painter.setPen(QPen(QColor(0, 210, 255, 205), 5, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for finger in fingers:
                chain = [palm, *finger]
                for a, b in zip(chain, chain[1:]):
                    painter.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))
                joints.extend(finger)
            painter.setPen(Qt.PenStyle.NoPen)
            for n, (x, y) in enumerate(joints):
                painter.setBrush(QColor(0, 218, 255, 225) if n % 2 == 0 else QColor(169, 91, 255, 230))
                painter.drawEllipse(int(x - 5), int(y - 5), 10, 10)
            simulated_pinch = index % 100 < 42
            tip = fingers[4][-1] if simulated_pinch else fingers[1][-1]
            painter.setPen(QPen(QColor(189, 101, 255, 190), 1, Qt.PenStyle.DashLine))
            painter.drawEllipse(int(tip[0] - 22), int(tip[1] - 22), 44, 44)
            painter.setPen(QColor("#89A9C0"))
            painter.setFont(QFont("Consolas", 9))
            painter.drawText(14, 24, "VISION PREVIEW  /  SYNTHETIC LANDMARK FEED")
            painter.end()
            badge = "[GESTURE DETECTED: PINCH TO DRAG]" if simulated_pinch else "[VISION SIMULATION: TRACKING HAND]"
            self.frame_ready.emit(image, badge)
            index += 1
            self.msleep(66)


class VisionPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image: QImage | None = None
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, image: QImage) -> None:
        self.image = image
        self.update()

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#071321"))
        if self.image:
            scaled = self.image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)
        painter.setPen(QPen(QColor(0, 210, 255, 130), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)


class VisionPanel(QFrame):
    """Optional simulated vision card; disabled by default."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SubCard")
        self.worker: VisionSimulationWorker | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        head = QHBoxLayout()
        title = QLabel("AI VISION  /  GESTURE CONTROL")
        title.setObjectName("SectionTitle")
        head.addWidget(title, 1)
        self.toggle = QCheckBox("Vision ON")
        self.toggle.setChecked(False)
        self.toggle.toggled.connect(self._toggle)
        head.addWidget(self.toggle)
        layout.addLayout(head)
        self.preview = VisionPreview()
        layout.addWidget(self.preview, 1)
        self.badge = QLabel("[VISION OFF]")
        self.badge.setObjectName("Accent")
        self.badge.setWordWrap(True)
        layout.addWidget(self.badge)
        note = QLabel("Synthetic landmark animation only · no camera access or actual gesture input")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)

    def _toggle(self, enabled: bool) -> None:
        if enabled:
            self.badge.setText("[VISION SIMULATION: STARTING]")
            self.worker = VisionSimulationWorker(self)
            self.worker.frame_ready.connect(self._on_frame)
            self.worker.start()
        else:
            self.stop()
            self.badge.setText("[VISION OFF]")

    def _on_frame(self, image: QImage, badge: str) -> None:
        self.preview.set_frame(image)
        self.badge.setText(badge)

    def stop(self) -> None:
        if self.worker:
            worker = self.worker
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(1200)
            worker.deleteLater()
        self.worker = None


class DropZone(QFrame):
    """Dashed file target for local bulk spreadsheets and documents."""

    files_dropped = pyqtSignal(list)
    ALLOWED = {".xlsx", ".csv", ".docx"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setStyleSheet("QFrame#DropZone { background: rgba(7, 19, 33, 220); border: 2px dashed #49728B; border-radius: 13px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 16)
        icon = QLabel("⇧")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("color:#54DFFF; font-size:34pt; font-weight:700;")
        layout.addWidget(icon)
        title = QLabel("DROP BULK CATALOG FILE")
        title.setObjectName("Accent")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("Excel · CSV · DOCX  |  Drag files here or browse")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        browse = QPushButton("Browse files")
        browse.clicked.connect(self._browse)
        layout.addWidget(browse)

    def _browse(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Select catalog files", "",
                                                 "Catalog files (*.xlsx *.csv *.docx)")
        if names:
            self.files_dropped.emit(names)

    def _paths(self, event: Any) -> list[str]:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        return [url.toLocalFile() for url in urls if url.isLocalFile()
                and Path(url.toLocalFile()).suffix.lower() in self.ALLOWED]

    def dragEnterEvent(self, event: Any) -> None:
        paths = self._paths(event)
        if paths:
            event.acceptProposedAction()
            self.setStyleSheet("QFrame#DropZone { background: rgba(0, 210, 255, 35); border: 2px dashed #00D2FF; border-radius: 13px; }")
        else:
            event.ignore()

    def dragLeaveEvent(self, event: Any) -> None:
        self.setStyleSheet("QFrame#DropZone { background: rgba(7, 19, 33, 220); border: 2px dashed #49728B; border-radius: 13px; }")

    def dropEvent(self, event: Any) -> None:
        self.setStyleSheet("QFrame#DropZone { background: rgba(7, 19, 33, 220); border: 2px dashed #49728B; border-radius: 13px; }")
        paths = self._paths(event)
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("GlassCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 11, 12, 12)
    layout.setSpacing(9)
    heading = QLabel(title.upper())
    heading.setObjectName("SectionTitle")
    layout.addWidget(heading)
    add_glow(frame, "#0A6B89", 18)
    return frame, layout


def _premium_build_ui(self: Any) -> None:
    """Replace presentation only; controller/backend methods stay on the app."""
    self.setWindowTitle("Omnichannel AI Manager V3.1")
    self.setMinimumSize(0, 0)
    self.setAcceptDrops(True)
    surface = QWidget()
    surface.setObjectName("MainSurface")
    outer = QVBoxLayout(surface)
    outer.setContentsMargins(10, 8, 10, 10)
    outer.setSpacing(9)
    self.title_bar = WindowTitleBar(self)
    outer.addWidget(self.title_bar)

    dashboard = QGridLayout()
    dashboard.setContentsMargins(2, 1, 2, 1)
    dashboard.setHorizontalSpacing(9)
    dashboard.setVerticalSpacing(9)
    dashboard.setColumnStretch(0, 2)
    dashboard.setColumnStretch(1, 4)
    dashboard.setColumnStretch(2, 3)
    dashboard.setRowStretch(0, 6)
    dashboard.setRowStretch(1, 4)

    stores_card, stores_layout = _card("Universal integration  ·  multi-store")
    for key, label in (("shopify", "Shopify"), ("amazon", "Amazon"), ("daraz", "Daraz"),
                       ("ebay", "eBay"), ("woocommerce", "WooCommerce"), ("tiktok_shop", "TikTok Shop")):
        row = QHBoxLayout()
        name = QLabel(label)
        name.setWordWrap(True)
        status = QLabel("●  ONLINE" if self.database.get_credentials(key) else "○  SETUP")
        status.setObjectName("StatusGood" if self.database.get_credentials(key) else "Muted")
        row.addWidget(name, 1)
        row.addWidget(status)
        stores_layout.addLayout(row)
    settings = QPushButton("⚙  OPEN SETTINGS")
    settings.setObjectName("Primary")
    settings.clicked.connect(self._open_settings)
    stores_layout.addStretch(1)
    stores_layout.addWidget(settings)
    dashboard.addWidget(stores_card, 0, 0, 1, 1)

    core_card, core_layout = _card("AI command core")
    core_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    self.orb = GlowingOrb()
    core_layout.addWidget(self.orb, 4)
    self.ai_status = QLabel("AWAITING COMMAND")
    self.ai_status.setObjectName("Accent")
    self.ai_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
    core_layout.addWidget(self.ai_status)
    command_row = QHBoxLayout()
    self.command = QLineEdit()
    self.command.setPlaceholderText("Ask OmniStore to analyze sales, list products, or send a report…")
    self.command.returnPressed.connect(self._submit_command)
    command_row.addWidget(self.command, 1)
    self.mic = QPushButton("🎙")
    self.mic.setObjectName("Mic")
    self.mic.setToolTip("Speak a command")
    self.mic.clicked.connect(self._voice_command)
    command_row.addWidget(self.mic)
    self.send = QPushButton("RUN  ↗")
    self.send.setObjectName("Primary")
    self.send.clicked.connect(self._submit_command)
    command_row.addWidget(self.send)
    core_layout.addLayout(command_row)
    self.vision_panel = VisionPanel()
    core_layout.addWidget(self.vision_panel, 3)
    dashboard.addWidget(core_card, 0, 1)

    analytics_card, analytics_layout = _card("Live multi-store analytics")
    pg.setConfigOption("background", None)
    pg.setConfigOption("foreground", "#9BCDE0")
    self.chart = pg.PlotWidget()
    self.chart.setBackground("#091523")
    self.chart.setTitle("Sales  ·  recent orders", color="#DDF7FF", size="10pt")
    self.chart.showGrid(x=True, y=True, alpha=.16)
    self.chart.getAxis("left").setPen(pg.mkPen("#64859B"))
    self.chart.getAxis("bottom").setPen(pg.mkPen("#64859B"))
    self.chart.setMinimumHeight(100)
    analytics_layout.addWidget(self.chart, 3)
    self.forecast_chart = pg.PlotWidget()
    self.forecast_chart.setBackground("#091523")
    self.forecast_chart.setTitle("AI inventory forecast  ·  demo trend", color="#DDF7FF", size="10pt")
    self.forecast_chart.showGrid(x=True, y=True, alpha=.16)
    self.forecast_chart.getAxis("left").setPen(pg.mkPen("#64859B"))
    self.forecast_chart.getAxis("bottom").setPen(pg.mkPen("#64859B"))
    self.forecast_chart.setMinimumHeight(100)
    self.forecast_chart.plot([0, 1, 2, 3, 4, 5, 6], [78, 66, 73, 52, 45, 31, 22],
                             pen=pg.mkPen("#A873FF", width=2),
                             symbol="o", symbolBrush="#00D2FF", symbolSize=6)
    analytics_layout.addWidget(self.forecast_chart, 3)
    self.orders = QTableWidget(0, 4)
    self.orders.setHorizontalHeaderLabels(["CHANNEL", "ORDER", "TOTAL", "STATUS"])
    self.orders.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    self.orders.verticalHeader().hide()
    self.orders.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    self.orders.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    self.orders.setMaximumHeight(155)
    analytics_layout.addWidget(self.orders, 2)
    dashboard.addWidget(analytics_card, 0, 2, 2, 1)

    bulk_card, bulk_layout = _card("Bulk processing")
    self.dropzone = DropZone()
    self.dropzone.files_dropped.connect(self._premium_files_dropped)
    bulk_layout.addWidget(self.dropzone, 1)
    self.progress = QProgressBar()
    self.progress.setRange(0, 100)
    self.progress.setValue(0)
    self.progress.setTextVisible(False)
    self.progress.hide()
    bulk_layout.addWidget(self.progress)
    dashboard.addWidget(bulk_card, 1, 0)

    logs_card, logs_layout = _card("Real-time AI activity")
    self.logs = QPlainTextEdit()
    self.logs.setReadOnly(True)
    self.logs.setMaximumBlockCount(2000)
    self.logs.setPlaceholderText("Marketplace events, AI actions, and upload progress appear here.")
    logs_layout.addWidget(self.logs, 1)
    dashboard.addWidget(logs_card, 1, 1)
    outer.addLayout(dashboard, 1)
    self.setCentralWidget(surface)
    self.setStyleSheet(PREMIUM_QSS)

    self.order_metric = self._metric_card("RECENT ORDERS", "0", "Across connected channels")
    self.platform_metric = self._metric_card("CONNECTED CHANNELS", "0", "Marketplace credentials")
    self.status_metric = self._metric_card("AGENT STATUS", "READY", "Gemini agent")
    # Keep controller metrics alive for its existing backend update methods.
    self.order_metric.hide()
    self.platform_metric.hide()
    self.status_metric.hide()
    self._premium_status_timer = QTimer(self)
    self._premium_status_timer.timeout.connect(lambda: self.ai_status.setText("AI AGENT  ·  PROCESSING" if self._busy else "AI AGENT  ·  READY"))
    self._premium_status_timer.start(180)
    QTimer.singleShot(0, self.showMaximized)


def _premium_files_dropped(self: Any, paths: list[str]) -> None:
    supported = [str(Path(path)) for path in paths
                 if Path(path).suffix.lower() in {".xlsx", ".csv", ".docx"}]
    if not supported:
        self._log("Choose an .xlsx, .csv, or .docx catalog file.")
        return
    configured = [name for name in self.database.get_platform_names()
                  if self.database.get_credentials(name)] if hasattr(self.database, "get_platform_names") else []
    if not configured:
        configured = [name for name in ("shopify", "daraz", "amazon", "ebay", "woocommerce", "tiktok_shop")
                      if self.database.get_credentials(name)]
    if not configured:
        QMessageBox.information(self, "Connect a store", "Save marketplace credentials in Settings before bulk processing.")
        return
    from omnistore.ui import TargetDialog
    dialog = TargetDialog(configured, self)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        targets = dialog.selection()
        if targets:
            self._begin_bulk(supported[0], targets)


def _premium_animate_orb(self: Any) -> None:
    if hasattr(self, "orb"):
        self.orb.set_thinking(bool(getattr(self, "_busy", False)))


def install_premium_ui() -> None:
    """Install this UI on the existing V3 window without replacing its backend."""
    try:
        from omnistore import ui as runtime
    except ImportError as exc:
        raise RuntimeError("This V3.1 visual layer requires the existing omnistore.ui application.") from exc
    window_class = getattr(runtime, "OmniStoreWindow", None)
    if window_class is None or not hasattr(runtime, "run"):
        raise RuntimeError("Could not locate OmniStoreWindow/run in omnistore.ui; no files were pushed.")
    window_class._build_ui = _premium_build_ui
    window_class._premium_files_dropped = _premium_files_dropped
    window_class._animate_orb = _premium_animate_orb
    previous_close = window_class.closeEvent
    if not getattr(window_class, "_premium_close_installed", False):
        def close_with_vision_cleanup(self: Any, event: Any) -> None:
            panel = getattr(self, "vision_panel", None)
            if panel:
                panel.stop()
            previous_close(self, event)
        window_class.closeEvent = close_with_vision_cleanup
        window_class._premium_close_installed = True

    settings_class = getattr(runtime, "SettingsDialog", None)
    if settings_class and not getattr(settings_class, "_premium_resize_installed", False):
        original_init = settings_class.__init__
        def responsive_settings_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)
            self.setMinimumSize(0, 0)
            screen = self.parentWidget().screen() if self.parentWidget() else QApplication.primaryScreen()
            if screen:
                area = screen.availableGeometry()
                self.resize(int(area.width() * .72), int(area.height() * .78))
        settings_class.__init__ = responsive_settings_init
        settings_class._premium_resize_installed = True

    runtime.APP_STYLE = PREMIUM_QSS


if __name__ == "__main__":
    # Preview mode uses the V3 application and applies the same visual patch.
    from omnistore.ui import run
    install_premium_ui()
    raise SystemExit(run())
