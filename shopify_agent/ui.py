"""Frameless PyQt6 store cockpit with animated status and live analytics."""

from __future__ import annotations

import math
import threading
from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtCore import (
    QEasingCurve, QObject, QPropertyAnimation, QRunnable, QThreadPool, QTimer,
    Qt, pyqtProperty, pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .ai_agent import StoreAgent
from .config import AppConfig, SettingsError, SettingsStore
from .native_effects import apply_windows_backdrop
from .shopify_client import ShopifyClient, ShopifyData
from .voice import transcribe_once

STYLE = """
* { font-family: "Segoe UI", "SF Pro Display", sans-serif; }
QMainWindow, QWidget#root { background: transparent; color: #edf3ff; }
QWidget { color: #edf3ff; }
QFrame#shell { background: rgba(10,13,20,246); border: 1px solid #273041; border-radius: 22px; }
QFrame#titlebar { background: rgba(15,19,29,225); border: 0; border-top-left-radius: 20px; border-top-right-radius: 20px; }
QFrame#sidebar { background: rgba(13,17,26,232); border: 0; border-bottom-left-radius: 20px; }
QFrame#panel, QFrame#metric { background: #151b27; border: 1px solid #273246; border-radius: 18px; }
QFrame#panel:hover, QFrame#metric:hover { border-color: #4f74a5; }
QLabel#eyebrow { color: #8b9ab2; font-size: 10px; font-weight: 800; letter-spacing: 2px; }
QLabel#metricValue { color: #f4f7ff; font-size: 25px; font-weight: 750; }
QLabel#muted { color: #9ba9bd; }
QLabel#accent { color: #79e3ff; font-weight: 700; }
QLabel#pageTitle { color: #f5f7ff; font-size: 22px; font-weight: 750; }
QLabel#brand { color: #e9f2ff; font-size: 13px; font-weight: 800; letter-spacing: 1px; }
QPushButton { color:#e9f2ff; background:#1a2231; border:1px solid #2b374c; border-radius:10px; padding:9px 13px; font-weight:650; }
QPushButton:hover { background:#24334a; border-color:#71dfff; }
QPushButton:pressed { background:#152132; }
QPushButton#primary { color:#07111c; background:#73e2fa; border:0; font-weight:800; }
QPushButton#primary:hover { background:#a2efff; }
QPushButton#nav { text-align:left; background:transparent; border:0; color:#aab8ce; padding:12px 15px; border-radius:11px; }
QPushButton#nav:hover, QPushButton#nav:checked { background:#1c293a; color:#85e7ff; }
QPushButton#windowControl { background:transparent; border:0; border-radius:8px; padding:6px 11px; }
QLineEdit { background:#0d121b; border:1px solid #2c394d; border-radius:10px; padding:11px 13px; color:#eff5ff; selection-background-color:#2589a1; }
QLineEdit:focus { border:1px solid #6fddf5; }
QLineEdit::placeholder { color:#748198; }
QTabWidget::pane { border:0; background:transparent; }
QTabBar::tab { background:#121925; color:#9caac0; padding:11px 17px; border:1px solid #263244; border-bottom:0; border-top-left-radius:9px; border-top-right-radius:9px; margin-right:5px; }
QTabBar::tab:selected { background:#1a2635; color:#7de5fb; border-color:#3b687d; }
QTableWidget { background:#101621; alternate-background-color:#151d2a; gridline-color:#263246; border:1px solid #29364a; border-radius:12px; selection-background-color:#17475a; }
QHeaderView::section { background:#172131; color:#9cadc3; border:0; padding:10px; font-weight:700; }
QCheckBox { spacing:8px; color:#d7e0ee; }
QCheckBox::indicator { width:17px; height:17px; }
QCheckBox::indicator:checked { background:#70ddf5; border:1px solid #70ddf5; border-radius:5px; }
QScrollArea { border:0; background:transparent; }
"""


class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    log = pyqtSignal(str)
    finished = pyqtSignal()


class FunctionWorker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.result.emit(self.function(self.signals.log.emit))
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()


class ApprovalRequest:
    def __init__(self, description: str):
        self.description = description
        self.event = threading.Event()
        self.accepted = False


class ApprovalBroker(QObject):
    requested = pyqtSignal(object)

    def ask(self, description: str) -> bool:
        request = ApprovalRequest(description)
        self.requested.emit(request)
        return request.event.wait(300) and request.accepted


class StatusOrb(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 60)
        self._pulse = 0.0
        self._thinking = False
        self.animation = QPropertyAnimation(self, b"pulse", self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(600)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.animation.setLoopCount(-1)

    def get_pulse(self):
        return self._pulse

    def set_pulse(self, value):
        self._pulse = float(value)
        self.update()

    pulse = pyqtProperty(float, fget=get_pulse, fset=set_pulse)

    def set_thinking(self, thinking: bool):
        self._thinking = thinking
        if thinking:
            self.animation.start()
        else:
            self.animation.stop()
            self._pulse = 0.1
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        breath = (math.sin(self._pulse * math.tau) + 1) / 2 if self._thinking else 0
        radius = 17 + int(5 * breath)
        glow = QRadialGradient(center, 30 + 3 * breath)
        glow.setColorAt(0, QColor(87, 225, 255, 100))
        glow.setColorAt(0.55, QColor(49, 152, 224, 35))
        glow.setColorAt(1, QColor(49, 152, 224, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, 30, 30)
        ring = QPen(QColor(93, 222, 255, 130 + int(50 * breath)), 1.2)
        painter.setPen(ring)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius + 4, radius + 4)
        core = QRadialGradient(center.x() - 5, center.y() - 6, radius + 5)
        core.setColorAt(0, QColor(231, 252, 255))
        core.setColorAt(0.3, QColor(119, 231, 255))
        core.setColorAt(0.8, QColor(49, 133, 212))
        core.setColorAt(1, QColor(27, 64, 126))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(core)
        painter.drawEllipse(center, radius, radius)


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—", color: str = "#79e3ff"):
        super().__init__()
        self.setObjectName("metric")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 14, 17, 14)
        caption = QLabel(title.upper())
        caption.setObjectName("eyebrow")
        self.value = QLabel(value)
        self.value.setObjectName("metricValue")
        self.value.setStyleSheet(f"color:{color};")
        layout.addWidget(caption)
        layout.addSpacing(4)
        layout.addWidget(self.value)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)

    def set_value(self, value: str):
        self.value.setText(value)


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("titlebar")
        self.setFixedHeight(52)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 12, 0)
        glyph = QLabel("◈")
        glyph.setObjectName("accent")
        glyph.setStyleSheet("font-size:20px;")
        brand = QLabel("SENTINEL  /  SHOPIFY INTELLIGENCE")
        brand.setObjectName("brand")
        version = QLabel("V2.0.0  ·  OPERATIONAL AI")
        version.setObjectName("eyebrow")
        layout.addWidget(glyph)
        layout.addWidget(brand)
        layout.addSpacing(15)
        layout.addWidget(version)
        layout.addStretch(1)
        for text, action, close in (
            ("—", window.showMinimized, False),
            ("□", window.toggle_maximize, False),
            ("×", window.close, True),
        ):
            button = QPushButton(text)
            button.setObjectName("windowControl")
            button.setFixedWidth(39)
            if close:
                button.setStyleSheet(
                    "QPushButton{background:transparent;border:0;border-radius:8px;padding:6px;color:#dce7f5}"
                    "QPushButton:hover{background:#bd3c55;color:white}"
                )
            button.clicked.connect(action)
            layout.addWidget(button)
        self.drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, _event):
        self.drag_offset = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sentinel — Shopify AI Manager")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(1450, 930)
        self.setMinimumSize(1120, 760)
        self.settings = SettingsStore()
        self.config = self.settings.load()
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(5)
        self.approvals = ApprovalBroker(self)
        self.approvals.requested.connect(self._show_approval)
        self._build_ui()
        QTimer.singleShot(250, lambda: apply_windows_backdrop(int(self.winId())))
        QTimer.singleShot(700, self.refresh_dashboard)
        QTimer.singleShot(900, self.refresh_analytics)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = QFrame()
        shell.setObjectName("shell")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(45)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 145))
        shell.setGraphicsEffect(shadow)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(shell)
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(TitleBar(self))
        body = QHBoxLayout()
        body.setSpacing(0)
        shell_layout.addLayout(body, 1)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 15)
        orb_row = QHBoxLayout()
        self.orb = StatusOrb()
        orb_row.addWidget(self.orb)
        identity = QVBoxLayout()
        name = QLabel("J.A.R.V.I.S")
        name.setStyleSheet("font-size:16px;font-weight:800;color:#eff8ff;letter-spacing:1px")
        identity.addWidget(name)
        sub = QLabel("STORE SYSTEMS")
        sub.setObjectName("eyebrow")
        identity.addWidget(sub)
        orb_row.addLayout(identity)
        side.addLayout(orb_row)
        side.addSpacing(22)
        workspace = QLabel("WORKSPACE")
        workspace.setObjectName("eyebrow")
        side.addWidget(workspace)
        self.nav = []
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._dashboard_page(), "Overview")
        self.tabs.addTab(self._analytics_page(), "Live Analytics")
        self.tabs.addTab(self._command_page(), "Command Center")
        self.tabs.addTab(self._settings_page(), "Settings")
        for index, (glyph, label) in enumerate([
            ("⌂", "Overview"),
            ("◌", "Live Analytics"),
            ("⌘", "Command Center"),
            ("⚙", "Settings"),
        ]):
            button = QPushButton(f"{glyph}     {label}")
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self.tabs.setCurrentIndex(i))
            side.addWidget(button)
            self.nav.append(button)
        self.nav[0].setChecked(True)
        side.addStretch(1)
        privacy = QLabel("PRIVATE BY DESIGN\nCredentials stay in your OS vault.")
        privacy.setObjectName("muted")
        privacy.setStyleSheet("font-size:10px")
        side.addWidget(privacy)
        body.addWidget(sidebar)

        content = QVBoxLayout()
        content.setContentsMargins(24, 20, 24, 20)
        content.setSpacing(13)
        body.addLayout(content, 1)
        head = QHBoxLayout()
        title_group = QVBoxLayout()
        eyebrow = QLabel("AUTONOMOUS STORE OPERATIONS")
        eyebrow.setObjectName("eyebrow")
        self.page_title = QLabel("Overview")
        self.page_title.setObjectName("pageTitle")
        title_group.addWidget(eyebrow)
        title_group.addWidget(self.page_title)
        head.addLayout(title_group)
        head.addStretch(1)
        self.system_status = QLabel("●  READY")
        self.system_status.setObjectName("accent")
        head.addWidget(self.system_status)
        content.addLayout(head)
        content.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(self._tab_changed)

    def _tab_changed(self, index: int):
        self.page_title.setText(self.tabs.tabText(index))
        for item, button in enumerate(self.nav):
            button.setChecked(item == index)

    @staticmethod
    def _panel(title: str, text: str = ""):
        frame = QFrame()
        frame.setObjectName("panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 13, 16, 13)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:14px;font-weight:750;color:#edf5ff")
        layout.addWidget(heading)
        if text:
            detail = QLabel(text)
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            layout.addWidget(detail)
        return frame, layout

    @staticmethod
    def _table(headers: list[str]):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.revenue = MetricCard("Revenue · 30 days")
        self.order_count = MetricCard("Recent orders", "—", "#ffffff")
        self.inventory_count = MetricCard("At-risk variants", "—", "#bd9fff")
        for card in (self.revenue, self.order_count, self.inventory_count):
            metrics.addWidget(card)
        layout.addLayout(metrics)
        middle = QHBoxLayout()
        middle.setSpacing(12)
        log_card, log_layout = self._panel("Live activity")
        self.activity = QTextEdit()
        self.activity.setReadOnly(True)
        self.activity.setMinimumHeight(200)
        self.activity.setStyleSheet(
            "QTextEdit{background:#0d121b;color:#c7d5e7;border:1px solid #29364a;"
            "border-radius:12px;padding:9px;font-family:Consolas;font-size:11px}"
        )
        log_layout.addWidget(self.activity, 1)
        middle.addWidget(log_card, 3)
        order_card, order_layout = self._panel("Recent Shopify orders")
        self.orders = self._table(["Order", "Customer", "Total", "Status"])
        order_layout.addWidget(self.orders, 1)
        refresh = QPushButton("Refresh orders")
        refresh.clicked.connect(self.refresh_dashboard)
        order_layout.addWidget(refresh, 0, Qt.AlignmentFlag.AlignRight)
        middle.addWidget(order_card, 4)
        layout.addLayout(middle, 1)
        controls = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText(
            "Ask J.A.R.V.I.S to analyze sales, forecast stock, or draft a campaign…"
        )
        self.command_input.returnPressed.connect(self.submit_command)
        controls.addWidget(self.command_input, 1)
        self.mic = QPushButton("◉  Speak")
        self.mic.setToolTip("Speak a command; it will be transcribed and sent to Gemini")
        self.mic.clicked.connect(self.start_voice_command)
        controls.addWidget(self.mic)
        self.run_button = QPushButton("Run command")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.submit_command)
        controls.addWidget(self.run_button)
        layout.addLayout(controls)
        note = QLabel(
            "External changes require desktop approval. Voice transcription uses Google's "
            "speech endpoint and requires internet and microphone access."
        )
        note.setObjectName("muted")
        note.setStyleSheet("font-size:10px")
        layout.addWidget(note)
        return page

    def _analytics_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        head = QHBoxLayout()
        note = QLabel("Live Shopify revenue and AI-assisted inventory run-out estimates.")
        note.setObjectName("muted")
        head.addWidget(note)
        head.addStretch(1)
        refresh = QPushButton("↻  Refresh live data")
        refresh.clicked.connect(self.refresh_analytics)
        head.addWidget(refresh)
        layout.addLayout(head)
        sales_card, sales_layout = self._panel("Sales trend · trailing 30 days")
        self.sales_plot = pg.PlotWidget()
        self._style_plot(self.sales_plot, "Revenue")
        self.sales_plot.setMinimumHeight(235)
        sales_layout.addWidget(self.sales_plot)
        layout.addWidget(sales_card, 3)
        inventory_card, inventory_layout = self._panel("Inventory forecast · days remaining")
        self.inventory_plot = pg.PlotWidget()
        self._style_plot(self.inventory_plot, "Days of inventory")
        self.inventory_plot.setMinimumHeight(235)
        inventory_layout.addWidget(self.inventory_plot)
        layout.addWidget(inventory_card, 3)
        caveat = QLabel(
            "Forecast uses trailing 90-day variant sales velocity. Seasonality, promotions, "
            "stock adjustments, untracked inventory and incomplete history affect accuracy."
        )
        caveat.setObjectName("muted")
        caveat.setStyleSheet("font-size:10px")
        layout.addWidget(caveat)
        return page

    @staticmethod
    def _style_plot(plot, label: str):
        plot.setBackground("#101621")
        plot.showGrid(x=True, y=True, alpha=0.14)
        plot.setLabel("left", label, color="#95a7c1")
        plot.getAxis("bottom").setTextPen("#8393aa")
        plot.getAxis("left").setTextPen("#8393aa")
        plot.getAxis("bottom").setPen("#344156")
        plot.getAxis("left").setPen("#344156")
        plot.setMenuEnabled(True)
        plot.setMouseEnabled(x=True, y=True)
        plot.getViewBox().setDefaultPadding(0.08)

    def _command_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        panel, panel_layout = self._panel("Talk to your store copilot")
        detail = QLabel(
            "Ask in plain language. The agent reads Shopify orders, estimates inventory run-out, "
            "researches competitor prices and prepares marketing copy. Product, email and "
            "WhatsApp actions are approval-gated by default."
        )
        detail.setWordWrap(True)
        detail.setObjectName("muted")
        panel_layout.addWidget(detail)
        layout.addWidget(panel)
        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setStyleSheet(
            "QTextEdit{background:#0d121b;color:#d2deee;border:1px solid #29364a;"
            "border-radius:14px;padding:14px;font-size:12px}"
        )
        layout.addWidget(self.transcript, 1)
        examples = QHBoxLayout()
        for prompt in (
            "Analyze today's sales",
            "Predict low inventory",
            "Suggest a market price for USB-C hub",
        ):
            button = QPushButton(prompt)
            button.clicked.connect(lambda _checked=False, value=prompt: self._prompt(value))
            examples.addWidget(button)
        layout.addLayout(examples)
        return page

    def _settings_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 7, 10)
        layout.setSpacing(10)
        self.config_fields: dict[str, QLineEdit] = {}
        self.secret_fields: dict[str, QLineEdit] = {}
        definitions = [
            ("Shopify store URL", "store_url", "https://your-store.myshopify.com", False),
            ("Shopify API version", "shopify_api_version", "2026-10", False),
            ("Gemini model", "gemini_model", "gemini-3.8-flash", False),
            ("WhatsApp sender Phone Number ID", "whatsapp_phone_number_id", "", False),
            ("WhatsApp Graph API version", "whatsapp_graph_api_version", "v23.0", False),
            ("WhatsApp approved template (optional)", "whatsapp_template_name", "", False),
            ("WhatsApp template language", "whatsapp_template_language", "en_US", False),
            ("SMTP server", "smtp_host", "smtp.example.com", False),
            ("SMTP port", "smtp_port", "587", False),
            ("From email address", "smtp_from_email", "store@example.com", False),
            ("Voice transcription language", "speech_language", "en-US", False),
            ("Gemini API key", "gemini_api_key", "Stored securely · leave blank to keep", True),
            ("Shopify Admin API token", "shopify_admin_api_token", "Stored securely · leave blank to keep", True),
            ("WhatsApp destination number", "whatsapp_number", "International format including country code", True),
            ("WhatsApp Cloud API token", "whatsapp_cloud_api_token", "Stored securely · leave blank to keep", True),
            ("SMTP username", "smtp_username", "Stored securely · leave blank to keep", True),
            ("SMTP password", "smtp_password", "Stored securely · leave blank to keep", True),
            ("Tavily search API key", "tavily_api_key", "Optional · enables competitor analysis", True),
        ]
        for label, key, placeholder, secret in definitions:
            panel, panel_layout = self._panel(label)
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            if secret:
                field.setEchoMode(QLineEdit.EchoMode.Password)
                self.secret_fields[key] = field
            else:
                field.setText(str(getattr(self.config, key)))
                self.config_fields[key] = field
            panel_layout.addWidget(field)
            layout.addWidget(panel)
        self.confirm = QCheckBox(
            "Require approval before creating products or sending email/WhatsApp"
        )
        self.confirm.setChecked(self.config.require_confirmation)
        layout.addWidget(self.confirm)
        info = QLabel(
            "Secrets are stored in Windows Credential Manager or macOS Keychain. Preferences "
            "are stored in your user config folder. Never commit credentials to Git."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        layout.addWidget(info)
        save = QPushButton("Save secure settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save_settings)
        layout.addWidget(save)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return page

    def toggle_maximize(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _log(self, text: str, command: bool = False):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {text}"
        self.activity.append(line)
        self.transcript.append(line)
        if command:
            self.tabs.setCurrentIndex(2)

    def _error(self, message: str):
        self._log(f"ERROR  {message}")
        QMessageBox.warning(self, "Shopify AI Manager", message)

    def _show_approval(self, request):
        answer = QMessageBox.question(
            self,
            "Approve store action",
            request.description,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        request.accepted = answer == QMessageBox.StandardButton.Yes
        request.event.set()

    def _submit(self, function, on_result, busy: str):
        self.system_status.setText(f"●  {busy.upper()}")
        task = FunctionWorker(function)
        task.signals.result.connect(on_result)
        task.signals.error.connect(self._error)
        task.signals.log.connect(self._log)
        task.signals.finished.connect(lambda: self.system_status.setText("●  READY"))
        self.thread_pool.start(task)

    def _shopify(self):
        return ShopifyClient(
            self.settings.load(),
            self.settings.get_secret("shopify_admin_api_token"),
        )

    def refresh_dashboard(self):
        self._log("Refreshing recent Shopify orders…")
        def load(_logger):
            return self._shopify().recent_orders()
        def show(rows):
            self.orders.setRowCount(len(rows))
            for row, order in enumerate(rows):
                values = (
                    order["name"], order["customer"],
                    f'{order["total"]} {order["currency"]}', order["status"],
                )
                for col, value in enumerate(values):
                    self.orders.setItem(row, col, QTableWidgetItem(str(value)))
            self.order_count.set_value(str(len(rows)))
            self._log(f"Loaded {len(rows)} recent orders.")
        self._submit(load, show, "syncing Shopify")

    def refresh_analytics(self):
        self._log("Refreshing sales and inventory…")
        def load(_logger):
            return self._shopify().analytics(lookback_days=90, max_pages=8)
        self._submit(load, self._show_analytics, "loading analytics")

    def _show_analytics(self, snapshot: ShopifyData):
        daily = sorted(snapshot.daily_sales.items())
        self.sales_plot.clear()
        recent = daily[-30:]
        if recent:
            x_values = list(range(len(recent)))
            y_values = [max(0, row[1]) for row in recent]
            self.sales_plot.plot(
                x_values, y_values, pen=pg.mkPen("#68e0fa", width=3),
                symbol="o", symbolSize=6, symbolBrush="#b8f5ff",
                fillLevel=0, brush=pg.mkBrush(85, 195, 239, 30),
            )
            self.sales_plot.getAxis("bottom").setTicks([[
                (index, row[0][5:]) for index, row in enumerate(recent)
            ]])
            total = sum(y_values)
            self.revenue.set_value(f"{snapshot.currency} {total:,.2f}".strip())
        else:
            self.sales_plot.setTitle("No recent Shopify sales", color="#9ba9bd")
            self.revenue.set_value("—")

        forecast = []
        for item in snapshot.variants:
            available = item.get("available")
            if not item.get("tracked") or available is None:
                continue
            units = snapshot.units_sold_by_variant.get(item["id"], 0)
            rate = units / max(1, snapshot.lookback_days)
            if rate > 0:
                forecast.append((item, min(365, int(available) / rate)))
        forecast.sort(key=lambda row: row[1])
        forecast = forecast[:10]
        self.inventory_count.set_value(str(len(forecast)) if forecast else "No tracked stock")
        self.inventory_plot.clear()
        if forecast:
            x = list(range(len(forecast)))
            days = [row[1] for row in forecast]
            bars = pg.BarGraphItem(
                x=x, height=days, width=0.66, brush=pg.mkBrush("#806af5"),
                pen=pg.mkPen("#a99aff", width=1),
            )
            self.inventory_plot.addItem(bars)
            self.inventory_plot.getAxis("bottom").setTicks([[
                (index, f'{row[0]["product"][:18]} · {row[0]["variant"][:10]}')
                for index, row in enumerate(forecast)
            ]])
            self.inventory_plot.setLabel("left", "Estimated days remaining", color="#95a7c1")
            self.inventory_plot.setXRange(-0.6, len(forecast) - 0.4)
            self.inventory_plot.setYRange(0, max(30, max(days) * 1.15))
        else:
            self.inventory_plot.setTitle(
                "No tracked variants with recent sales to forecast", color="#9ba9bd"
            )
        self._log(f"Analytics refreshed: {len(daily)} sales days, {len(snapshot.variants)} variants.")

    def submit_command(self):
        prompt = self.command_input.text().strip()
        if not prompt:
            return
        self.command_input.clear()
        self._log(f"YOU  {prompt}", command=True)
        self.run_button.setEnabled(False)
        self.mic.setEnabled(False)
        self.orb.set_thinking(True)
        self.system_status.setText("●  THINKING")
        def work(log_callback):
            agent = StoreAgent(
                self.settings.load(), self.settings, self.approvals.ask, log_callback
            )
            return agent.run(prompt)
        def done(response):
            self._log(f"J.A.R.V.I.S  {response}", command=True)
        task = FunctionWorker(work)
        task.signals.result.connect(done)
        task.signals.error.connect(self._error)
        task.signals.log.connect(self._log)
        task.signals.finished.connect(self._agent_finished)
        self.thread_pool.start(task)

    def _agent_finished(self):
        self.orb.set_thinking(False)
        self.system_status.setText("●  READY")
        self.run_button.setEnabled(True)
        self.mic.setEnabled(True)

    def _prompt(self, value: str):
        self.command_input.setText(value)
        self.submit_command()

    def start_voice_command(self):
        self.mic.setEnabled(False)
        self.mic.setText("◉  Listening…")
        self.system_status.setText("●  LISTENING")
        self._log("Microphone active. Speak one command.")
        language = self.config.speech_language
        task = FunctionWorker(lambda _logger: transcribe_once(language))
        def heard(text):
            self.command_input.setText(text)
            self._log(f"VOICE  {text}", command=True)
            self.mic.setText("◉  Speak")
            self.mic.setEnabled(True)
            self.submit_command()
        task.signals.result.connect(heard)
        task.signals.error.connect(self._error)
        task.signals.finished.connect(self._voice_finished)
        self.thread_pool.start(task)

    def _voice_finished(self):
        self.mic.setText("◉  Speak")
        self.mic.setEnabled(True)
        self.system_status.setText("●  READY")

    def save_settings(self):
        try:
            port = int(self.config_fields["smtp_port"].text().strip() or "587")
            if not 1 <= port <= 65535:
                raise ValueError("SMTP port must be between 1 and 65535.")
            config = AppConfig(
                store_url=self.config_fields["store_url"].text().strip(),
                shopify_api_version=self.config_fields["shopify_api_version"].text().strip() or "2026-10",
                gemini_model=self.config_fields["gemini_model"].text().strip() or "gemini-3.8-flash",
                whatsapp_phone_number_id=self.config_fields["whatsapp_phone_number_id"].text().strip(),
                whatsapp_graph_api_version=self.config_fields["whatsapp_graph_api_version"].text().strip() or "v23.0",
                whatsapp_template_name=self.config_fields["whatsapp_template_name"].text().strip(),
                whatsapp_template_language=self.config_fields["whatsapp_template_language"].text().strip() or "en_US",
                smtp_host=self.config_fields["smtp_host"].text().strip(),
                smtp_port=port,
                smtp_from_email=self.config_fields["smtp_from_email"].text().strip(),
                speech_language=self.config_fields["speech_language"].text().strip() or "en-US",
                require_confirmation=self.confirm.isChecked(),
            )
            secrets = {
                name: field.text()
                for name, field in self.secret_fields.items()
                if field.text()
            }
            self.settings.save(config, secrets)
            self.config = config
            for field in self.secret_fields.values():
                field.clear()
            self._log("Settings saved securely to your user profile.")
            QMessageBox.information(self, "Settings saved", "Preferences and credentials were saved securely.")
        except (ValueError, SettingsError) as exc:
            self._error(str(exc))


def run() -> int:
    pg.setConfigOptions(antialias=True, useOpenGL=False)
    app = QApplication([])
    app.setApplicationName("Shopify AI Manager")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()

