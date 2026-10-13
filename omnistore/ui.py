"""Premium single-screen desktop UI and settings modal."""

from __future__ import annotations

import json
import logging
import queue
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pyqtgraph as pg
import speech_recognition as sr
from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QProgressBar,
)

from .adapters import ADAPTERS
from .database import SecureDatabase
from .services.agent import GeminiAgent
from .services.bulk import SHEETS_RE
from .services.channels import OrderIntegrations
from .services.supabase_cloud import SupabaseCloudStore, SupabaseCredentials

LOG = logging.getLogger(__name__)
PLATFORMS = ["shopify", "daraz", "amazon", "ebay", "woocommerce", "tiktok_shop"]
PLATFORM_TITLES = {"shopify": "Shopify", "daraz": "Daraz", "amazon": "Amazon",
                   "ebay": "eBay", "woocommerce": "WooCommerce", "tiktok_shop": "TikTok Shop"}

APP_STYLE = """
QWidget { background:#080b12; color:#eaf1ff; font-family:'Segoe UI'; font-size:10pt; }
QMainWindow { background:#080b12; }
QFrame#Card { background:#111722; border:1px solid #202b3b; border-radius:16px; }
QFrame#TopBar { background:#080b12; border-bottom:1px solid #202b3b; }
QLabel#Brand { color:#f4f7ff; font-size:16pt; font-weight:700; }
QLabel#Muted { color:#8592a7; }
QLabel#Section { color:#dce8ff; font-size:11pt; font-weight:600; }
QLabel#Metric { color:#61e8d4; font-size:18pt; font-weight:700; }
QPushButton { background:#172437; color:#eaf1ff; border:1px solid #304361; border-radius:10px; padding:9px 14px; }
QPushButton:hover { background:#203653; border-color:#57dccc; }
QPushButton#Primary { background:#15b8ac; border:0; color:#061014; font-weight:700; }
QPushButton#Primary:hover { background:#52e5d4; }
QPushButton#Mic { background:#251932; border:1px solid #d977ff; border-radius:24px; min-width:46px; min-height:46px; font-size:16pt; }
QPushButton#Mic:hover { background:#49245b; }
QLineEdit, QPlainTextEdit, QListWidget, QTableWidget { background:#0b111b; border:1px solid #243144; border-radius:9px; padding:8px; selection-background-color:#176a70; }
QLineEdit:focus, QPlainTextEdit:focus { border:1px solid #22d3c5; }
QTableWidget { gridline-color:#202b3b; }
QHeaderView::section { background:#151d29; color:#91a5c1; border:0; padding:7px; }
QProgressBar { background:#101723; border:0; border-radius:4px; height:8px; text-align:center; }
QProgressBar::chunk { background:#22d3c5; border-radius:4px; }
QTabWidget::pane { border:1px solid #243144; border-radius:10px; top:-1px; }
QTabBar::tab { background:#101723; color:#9aa9bf; padding:10px 14px; margin-right:3px; border-top-left-radius:8px; border-top-right-radius:8px; }
QTabBar::tab:selected { color:#dffcf8; background:#183234; border-bottom:2px solid #22d3c5; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:16px; height:16px; }
"""


class SettingsDialog(QDialog):
    """Credential entry modal; every field is stored encrypted by SecureDatabase."""

    PLATFORM_FIELDS: dict[str, list[tuple[str, str, bool]]] = {
        "Shopify": [("Store URL", "store_url", False), ("Admin API token", "admin_token", True),
                    ("API version", "api_version", False), ("Webhook signing secret", "webhook_secret", True)],
        "Daraz": [("API base URL", "api_base", False), ("App key", "app_key", True),
                  ("App secret", "app_secret", True), ("User ID", "user_id", False),
                  ("Region", "region", False)],
        "Amazon": [("LWA client ID", "lwa_client_id", True), ("LWA client secret", "lwa_client_secret", True),
                   ("LWA refresh token", "lwa_refresh_token", True), ("AWS access key", "aws_access_key", True),
                   ("AWS secret key", "aws_secret_key", True), ("AWS session token (optional)", "aws_session_token", True),
                   ("Role ARN (optional)", "role_arn", False), ("Seller ID", "seller_id", False),
                   ("Marketplace ID", "marketplace_id", False), ("Region (na/eu/fe)", "region", False)],
        "eBay": [("OAuth access token", "access_token", True), ("Marketplace ID", "marketplace_id", False),
                 ("Category ID", "category_id", False), ("Merchant location key", "location_key", False),
                 ("Fulfillment policy ID", "fulfillment_policy_id", False),
                 ("Payment policy ID", "payment_policy_id", False),
                 ("Return policy ID", "return_policy_id", False)],
        "WooCommerce": [("Store URL", "store_url", False), ("Consumer key", "consumer_key", True),
                        ("Consumer secret", "consumer_secret", True), ("Webhook signing secret", "webhook_secret", True)],
        "TikTok Shop": [("App key", "app_key", True), ("App secret", "app_secret", True),
                        ("Access token", "access_token", True), ("Shop ID", "shop_id", False),
                        ("Region", "region", False)],
    }

    def __init__(self, database: SecureDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = database
        self.setWindowTitle("OmniStore · Settings")
        self.resize(860, 670)
        self.setModal(True)
        outer = QVBoxLayout(self)
        heading = QLabel("Workspace settings")
        heading.setObjectName("Brand")
        outer.addWidget(heading)
        tabs = QTabWidget()
        tabs.setUsesScrollButtons(True)
        outer.addWidget(tabs, 1)
        self.inputs: dict[str, dict[str, QLineEdit]] = {}
        self.checks: dict[str, QCheckBox] = {}
        self._add_general(tabs)
        for title in ("Shopify", "Daraz", "Amazon", "eBay", "WooCommerce", "TikTok Shop"):
            self._add_platform(tabs, title)
        self._add_google(tabs)
        self._add_supabase(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _field(self, form: QFormLayout, group: str, key: str, label: str, secret: bool,
               current: dict[str, Any]) -> None:
        widget = QLineEdit()
        if secret:
            widget.setEchoMode(QLineEdit.EchoMode.Password)
            if current.get(key):
                widget.setPlaceholderText("Saved securely · leave blank to keep current value")
        else:
            widget.setText(str(current.get(key, "")))
        self.inputs.setdefault(group, {})[key] = widget
        form.addRow(label, widget)

    def _add_general(self, tabs: QTabWidget) -> None:
        page = QWidget()
        form = QFormLayout(page)
        form.setVerticalSpacing(12)
        general = self.db.get_credentials("general")
        whatsapp = self.db.get_credentials("whatsapp")
        smtp = self.db.get_credentials("smtp")
        for key, label, secret in [
            ("recipient_number", "WhatsApp recipient number", False),
            ("phone_number_id", "Meta sender phone number ID", False),
            ("access_token", "Meta WhatsApp access token", True),
            ("api_version", "Meta Graph API version", False),
        ]:
            self._field(form, "whatsapp", key, label, secret, whatsapp)
        self._field(form, "smtp", "host", "SMTP host", False, smtp)
        self._field(form, "smtp", "port", "SMTP port", False, smtp)
        for key, label in [("username", "SMTP username"), ("password", "SMTP password"),
                           ("from_address", "From email address"), ("reply_subject", "Reply subject")]:
            self._field(form, "smtp", key, label, key == "password", smtp)
        self._field(form, "general", "webhook_port", "Local webhook port", False, general)
        self._field(form, "general", "poll_seconds", "Order poll interval (seconds)", False, general)
        auto_send = QCheckBox("Allow AI-drafted customer replies to send automatically via SMTP")
        auto_send.setChecked(bool(general.get("auto_send_email", False)))
        self.checks["auto_send_email"] = auto_send
        form.addRow("Email safety", auto_send)
        webhook = QCheckBox("Start HMAC-verified local Shopify/WooCommerce webhook receiver")
        webhook.setChecked(bool(general.get("enable_webhooks", True)))
        self.checks["enable_webhooks"] = webhook
        form.addRow("Webhooks", webhook)
        note = QLabel("Secrets are encrypted in the local SQLite database. Key material stays in Windows Credential Manager or macOS Keychain.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow(note)
        tabs.addTab(page, "General")

    def _add_platform(self, tabs: QTabWidget, title: str) -> None:
        platform = title.lower().replace(" ", "_")
        page = QWidget()
        form = QFormLayout(page)
        form.setVerticalSpacing(12)
        current = self.db.get_credentials(platform)
        for label, key, secret in self.PLATFORM_FIELDS[title]:
            self._field(form, platform, key, label, secret, current)
        note = QLabel("TikTok Shop and Daraz are scaffold adapters in this release; credentials can be saved, but live API actions stay disabled until regional signing/OAuth is implemented.") if platform in ("tiktok_shop", "daraz") else QLabel("Use a least-privilege app token. Product creation is a draft where supported by the platform API.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow(note)
        tabs.addTab(page, title)

    def _add_google(self, tabs: QTabWidget) -> None:
        page = QWidget()
        form = QFormLayout(page)
        current = self.db.get_credentials("google")
        self._field(form, "google", "api_key", "Gemini / Google API key", True, current)
        self._field(form, "google", "model_name", "Gemini model ID", False, current)
        service_json = QPlainTextEdit()
        service_json.setPlaceholderText("Optional Google service-account JSON for private Sheets (stored encrypted).")
        if current.get("service_account_json"):
            service_json.setPlaceholderText("Service account saved securely · enter replacement JSON or leave unchanged")
        self.json_input = service_json
        form.addRow("Google Sheets service account JSON", service_json)
        note = QLabel("Gemini 1.5 Pro is retired from the current Gemini API catalog. The default model is configurable and set to gemini-3.8-flash; enter a model ID supported by your API key.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow(note)
        tabs.addTab(page, "Google API Credentials")

    def _add_supabase(self, tabs: QTabWidget) -> None:
        page = QWidget()
        form = QFormLayout(page)
        form.setVerticalSpacing(12)
        current = self.db.get_credentials("supabase")
        self._field(form, "supabase", "project_url", "Project URL", False, current)
        self._field(form, "supabase", "publishable_key", "Publishable / anon key", True, current)
        self._field(form, "supabase", "email", "Supabase Auth email", False, current)
        self._field(form, "supabase", "password", "Supabase Auth password", True, current)
        enabled = QCheckBox("Enable encrypted cloud sync for safe activity summaries and daily sales aggregates")
        enabled.setChecked(bool(current.get("enabled", False)))
        self.checks["supabase_enabled"] = enabled
        form.addRow("Cloud sync", enabled)
        note = QLabel(
            "Only a publishable (or legacy anon) key is accepted. Never paste a secret/service-role key. "
            "Credentials are encrypted in the local OS-keychain-backed database. Cloud tables must be "
            "created with the included Supabase setup SQL; RLS limits records to the signed-in user."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        form.addRow(note)
        tabs.addTab(page, "Supabase Cloud")

    def _save_group(self, group: str) -> dict[str, Any]:
        saved = self.db.get_credentials(group)
        for key, widget in self.inputs.get(group, {}).items():
            value = widget.text().strip()
            if value:
                saved[key] = value
        return saved

    def _save(self) -> None:
        try:
            supabase = self._save_group("supabase")
            supabase["enabled"] = self.checks["supabase_enabled"].isChecked()
            if supabase["enabled"]:
                SupabaseCredentials.from_mapping(supabase)
            for group in ("whatsapp", "smtp", "shopify", "daraz", "amazon", "ebay",
                          "woocommerce", "tiktok_shop", "google"):
                if group in self.inputs:
                    self.db.save_credentials(group, self._save_group(group))
            self.db.save_credentials("supabase", supabase)
            general = self._save_group("general")
            for key, checkbox in self.checks.items():
                if key != "supabase_enabled":
                    general[key] = checkbox.isChecked()
            general.setdefault("webhook_port", "8787")
            general.setdefault("poll_seconds", "180")
            self.db.save_credentials("general", general)
            google = self._save_group("google")
            service_json = self.json_input.toPlainText().strip()
            if service_json:
                parsed = json.loads(service_json)
                if not isinstance(parsed, dict) or "client_email" not in parsed:
                    raise ValueError("Service account JSON must be an object containing client_email")
                google["service_account_json"] = parsed
            self.db.save_credentials("google", google)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save settings", str(exc))
            return
        self.accept()


class WorkThread(QThread):
    log = pyqtSignal(str)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, database: SecureDatabase, prompt: str = "", bulk_source: str = "",
                 targets: list[str] | None = None) -> None:
        super().__init__()
        self.database, self.prompt, self.bulk_source = database, prompt, bulk_source
        self.targets = targets or []

    def run(self) -> None:
        try:
            agent = GeminiAgent(self.database, self.log.emit, self.progress.emit)
            if self.bulk_source:
                result = agent.bulk(self.bulk_source, self.targets)
                self.done.emit(json.dumps(result, ensure_ascii=False, default=str))
            else:
                self.done.emit(agent.run(self.prompt))
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceThread(QThread):
    transcript = pyqtSignal(str)
    failed = pyqtSignal(str)

    def run(self) -> None:
        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = recognizer.listen(source, timeout=6, phrase_time_limit=18)
            self.transcript.emit(recognizer.recognize_google(audio))
        except sr.WaitTimeoutError:
            self.failed.emit("No speech was detected before the microphone timed out.")
        except sr.UnknownValueError:
            self.failed.emit("I could not understand that recording. Try again.")
        except Exception as exc:
            self.failed.emit(f"Voice capture unavailable: {exc}")


class SupabaseSyncThread(QThread):
    """Keep Supabase authentication and all cloud I/O off the Qt GUI thread."""

    status = pyqtSignal(str)
    snapshot = pyqtSignal(list, list)

    def __init__(self, database: SecureDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database = database
        self._commands: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._stop_requested = False

    def configure(self, values: dict[str, Any]) -> None:
        self._commands.put(("configure", dict(values)))

    def record_activity(self, event_type: str, message: str) -> None:
        self._commands.put(("activity", (event_type, message, str(uuid.uuid4()))))

    def request_stop(self) -> None:
        self._stop_requested = True
        self._commands.put(("stop", None))

    def run(self) -> None:
        configuration: dict[str, Any] = {}
        cloud: SupabaseCloudStore | None = None
        pending: list[tuple[str, str, str]] = []
        retry_at = 0.0
        retry_delay = 15.0
        next_analytics = 0.0
        next_snapshot = 0.0
        disabled_reported = False

        while not self._stop_requested:
            try:
                command, payload = self._commands.get(timeout=0.5)
            except queue.Empty:
                command, payload = "", None

            if command == "stop":
                break
            if command == "configure":
                if cloud:
                    cloud.close()
                    cloud = None
                configuration = payload or {}
                pending.clear()  # Never send queued data across account changes.
                retry_at = 0.0
                retry_delay = 15.0
                disabled_reported = False
            elif command == "activity" and len(pending) < 500:
                pending.append(payload)

            if self._stop_requested:
                break
            if not configuration.get("enabled"):
                if not disabled_reported:
                    self.status.emit("Cloud sync disabled")
                    disabled_reported = True
                continue

            now = time.monotonic()
            if cloud is None:
                if now < retry_at:
                    continue
                try:
                    credentials = SupabaseCredentials.from_mapping(configuration)
                    cloud = SupabaseCloudStore(credentials)
                    cloud.connect()
                    self.status.emit("Supabase connected · RLS-protected sync")
                    retry_delay = 15.0
                    next_analytics = next_snapshot = 0.0
                except Exception as exc:
                    cloud = None
                    detail = str(exc) if isinstance(exc, ValueError) else "Sign-in failed; check Auth settings"
                    self.status.emit(f"Supabase offline · {detail}")
                    retry_at = now + retry_delay
                    retry_delay = min(retry_delay * 2, 300.0)
                    continue

            try:
                if pending:
                    event_type, message, event_id = pending[0]
                    cloud.record_activity(event_type, message, event_id)
                    pending.pop(0)
                now = time.monotonic()
                if now >= next_analytics:
                    cloud.upsert_daily_sales(self.database.daily_sales(90))
                    next_analytics = now + 60.0
                if now >= next_snapshot:
                    activities, analytics = cloud.fetch_snapshot()
                    self.snapshot.emit(activities, analytics)
                    next_snapshot = now + 12.0
            except Exception:
                # Keep unsent activity for idempotent retry. Hide SDK details
                # because network errors can include remote request metadata.
                self.status.emit("Supabase sync needs attention · check table setup and RLS")
                cloud.close()
                cloud = None
                retry_at = time.monotonic() + retry_delay
                retry_delay = min(retry_delay * 2, 300.0)

        if cloud:
            cloud.close()
        self.status.emit("Cloud sync stopped")


class TargetDialog(QDialog):
    def __init__(self, configured: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose listing destinations")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Bulk rows are created sequentially on each selected connected store."))
        self.boxes: dict[str, QCheckBox] = {}
        for platform in configured:
            checkbox = QCheckBox(PLATFORM_TITLES.get(platform, platform.title()))
            checkbox.setChecked(True)
            layout.addWidget(checkbox)
            self.boxes[platform] = checkbox
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self) -> list[str]:
        return [key for key, box in self.boxes.items() if box.isChecked()]


class OmniStoreWindow(QMainWindow):
    log_signal = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OmniStore AI Manager")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.resize(1460, 900)
        self.setMinimumSize(1120, 720)
        self.setAcceptDrops(True)
        self._drag_position = None
        self._busy = False
        self.database = SecureDatabase()
        self._cloud_seen_ids: set[str] = set()
        self._cloud_analytics: list[dict[str, Any]] = []
        self._cloud_close_requested = False
        self.log_signal.connect(self._append_log)
        self.integration_service: OrderIntegrations | None = None
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self.cloud_worker = SupabaseSyncThread(self.database, self)
        self.cloud_worker.status.connect(self._cloud_status)
        self.cloud_worker.snapshot.connect(self._cloud_snapshot)
        self.cloud_worker.start()
        self._configure_cloud_sync()
        self._refresh_orders()
        self.orders_timer = QTimer(self)
        self.orders_timer.timeout.connect(self._refresh_orders)
        self.orders_timer.start(10000)
        QTimer.singleShot(800, self._start_integrations)

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 12, 18, 18)
        outer.setSpacing(14)
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(4, 2, 4, 8)
        brand = QLabel("◈  OMNISTORE")
        brand.setObjectName("Brand")
        bar_layout.addWidget(brand)
        bar_layout.addWidget(QLabel("AI COMMERCE CONTROL CENTER  ·  V3.0"), 1)
        settings = QPushButton("⚙  Settings")
        settings.clicked.connect(self._open_settings)
        bar_layout.addWidget(settings)
        minimize = QPushButton("—")
        minimize.setFixedWidth(40)
        minimize.clicked.connect(self.showMinimized)
        close = QPushButton("×")
        close.setFixedWidth(40)
        close.clicked.connect(self.close)
        bar_layout.addWidget(minimize)
        bar_layout.addWidget(close)
        outer.addWidget(bar)

        hero = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("Your commerce. One command away.")
        title.setObjectName("Brand")
        subtitle = QLabel("Orchestrate catalogs, orders, and customer operations across connected markets.")
        subtitle.setObjectName("Muted")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        hero.addLayout(title_block, 1)
        self.orb = QLabel("✦")
        self.orb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.orb.setFixedSize(52, 52)
        self.orb.setStyleSheet("QLabel { color:#8b7bff; background:#211c3a; border:1px solid #7568ff; border-radius:26px; font-size:21pt; }")
        hero.addWidget(self.orb)
        outer.addLayout(hero)

        metrics = QHBoxLayout()
        self.order_metric = self._metric_card("RECENT ORDERS", "0", "Across webhook and polling sources")
        self.platform_metric = self._metric_card("CONNECTED CHANNELS", "0", "Configure marketplace access in Settings")
        self.status_metric = self._metric_card("AGENT STATUS", "READY", "Gemini model configured in Settings")
        metrics.addWidget(self.order_metric)
        metrics.addWidget(self.platform_metric)
        metrics.addWidget(self.status_metric)
        outer.addLayout(metrics)

        panels = QHBoxLayout()
        left = QFrame()
        left.setObjectName("Card")
        left_layout = QVBoxLayout(left)
        header = QHBoxLayout()
        log_title = QLabel("Live activity")
        log_title.setObjectName("Section")
        self.log_state = QLabel("●  Monitoring local activity")
        self.log_state.setObjectName("Muted")
        header.addWidget(log_title)
        header.addStretch(1)
        header.addWidget(self.log_state)
        left_layout.addLayout(header)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(2000)
        self.logs.setPlaceholderText("AI activity and marketplace events appear here.")
        left_layout.addWidget(self.logs, 1)
        self.dropzone = QFrame()
        self.dropzone.setStyleSheet("QFrame { background:#0d1520; border:1px dashed #3b5676; border-radius:12px; }")
        drop_layout = QVBoxLayout(self.dropzone)
        self.drop_label = QLabel("⇧   Drop .xlsx, .csv, or .docx files here\nGoogle Sheets URLs work in the command bar")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setObjectName("Muted")
        drop_layout.addWidget(self.drop_label)
        left_layout.addWidget(self.dropzone)
        command_row = QHBoxLayout()
        self.command = QLineEdit()
        self.command.setPlaceholderText("Ask OmniStore… e.g. ‘List this on all platforms’ or paste a Sheets URL")
        self.command.returnPressed.connect(self._submit_command)
        command_row.addWidget(self.command, 1)
        self.mic = QPushButton("🎙")
        self.mic.setObjectName("Mic")
        self.mic.setToolTip("Speak a command")
        self.mic.clicked.connect(self._voice_command)
        command_row.addWidget(self.mic)
        self.send = QPushButton("Run command  ↗")
        self.send.setObjectName("Primary")
        self.send.clicked.connect(self._submit_command)
        command_row.addWidget(self.send)
        left_layout.addLayout(command_row)

        right = QFrame()
        right.setObjectName("Card")
        right_layout = QVBoxLayout(right)
        right_header = QHBoxLayout()
        recent_title = QLabel("Recent orders")
        recent_title.setObjectName("Section")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh_orders)
        right_header.addWidget(recent_title)
        right_header.addStretch(1)
        right_header.addWidget(refresh)
        right_layout.addLayout(right_header)
        self.orders = QTableWidget(0, 4)
        self.orders.setHorizontalHeaderLabels(["CHANNEL", "ORDER", "TOTAL", "STATUS"])
        self.orders.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.orders.verticalHeader().hide()
        self.orders.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.orders.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        right_layout.addWidget(self.orders, 1)
        chart_title = QLabel("Order volume  ·  recent events")
        chart_title.setObjectName("Muted")
        right_layout.addWidget(chart_title)
        self.chart = pg.PlotWidget()
        self.chart.setBackground("#111722")
        self.chart.showGrid(x=True, y=True, alpha=0.18)
        self.chart.getAxis("left").setPen(pg.mkPen("#66758d"))
        self.chart.getAxis("bottom").setPen(pg.mkPen("#66758d"))
        self.chart.setMinimumHeight(180)
        right_layout.addWidget(self.chart)
        panels.addWidget(left, 7)
        panels.addWidget(right, 5)
        outer.addLayout(panels, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.setCentralWidget(root)

        self._pulse = 0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._animate_orb)
        self._pulse_timer.start(70)

    def _metric_card(self, heading: str, value: str, detail: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        label = QLabel(heading)
        label.setObjectName("Muted")
        value_label = QLabel(value)
        value_label.setObjectName("Metric")
        detail_label = QLabel(detail)
        detail_label.setObjectName("Muted")
        detail_label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)
        card.value_label = value_label  # type: ignore[attr-defined]
        card.detail_label = detail_label  # type: ignore[attr-defined]
        return card

    def _animate_orb(self) -> None:
        self._pulse = (self._pulse + 1) % 80
        if self._busy:
            intensity = 0.50 + abs(40 - self._pulse) / 100
            self.orb.setStyleSheet(f"QLabel {{ color:#f6eaff; background:rgba(91,43,124,{intensity:.2f}); border:2px solid #d977ff; border-radius:26px; font-size:21pt; }}")
        else:
            self.orb.setStyleSheet("QLabel { color:#8b7bff; background:#211c3a; border:1px solid #7568ff; border-radius:26px; font-size:21pt; }")

    def _log(self, message: str) -> None:
        self.log_signal.emit(message)

    def _append_log(self, message: str) -> None:
        self.logs.appendPlainText(f"{datetime.now().strftime('%H:%M:%S')}  {message}")
        scrollbar = self.logs.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _configure_cloud_sync(self) -> None:
        self.cloud_worker.configure(self.database.get_credentials("supabase"))

    def _record_cloud_activity(self, event_type: str, message: str) -> None:
        if hasattr(self, "cloud_worker"):
            self.cloud_worker.record_activity(event_type, message)

    def _cloud_status(self, message: str) -> None:
        self.log_state.setText(f"●  {message}")

    def _cloud_snapshot(self, activities: list, analytics: list) -> None:
        self._cloud_analytics = [row for row in analytics if isinstance(row, dict)]
        for row in reversed(activities):
            if not isinstance(row, dict):
                continue
            event_id = str(row.get("id") or "")
            if event_id and event_id not in self._cloud_seen_ids:
                self._cloud_seen_ids.add(event_id)
                self._append_log(f"☁  {row.get('message', 'Cloud activity')}")
        if len(self._cloud_seen_ids) > 500:
            self._cloud_seen_ids = set(list(self._cloud_seen_ids)[-250:])
        self._paint_cloud_analytics()

    def _paint_cloud_analytics(self) -> None:
        if not self._cloud_analytics:
            return
        by_currency: dict[str, list[dict[str, Any]]] = {}
        for row in self._cloud_analytics:
            currency = str(row.get("currency") or "UNK")
            by_currency.setdefault(currency, []).append(row)
        currency = max(by_currency, key=lambda code: sum(float(r.get("gross_sales") or 0) for r in by_currency[code]))
        rows = sorted(by_currency[currency], key=lambda r: str(r.get("sales_date") or ""))
        values = [float(row.get("gross_sales") or 0) for row in rows]
        self.chart.clear()
        self.chart.plot(list(range(len(values))), values, pen=pg.mkPen("#22d3c5", width=2),
                        symbol="o", symbolSize=7, symbolBrush="#68f0df")
        self.chart.setTitle(f"Cloud sales · {currency}")
        self.chart.setLabel("left", f"Sales ({currency})")
        self.chart.setLabel("bottom", "Daily totals · Supabase")

    def _open_settings(self) -> None:
        if SettingsDialog(self.database, self).exec() == QDialog.DialogCode.Accepted:
            self._configure_cloud_sync()
            self._log("Encrypted workspace settings saved")
            self._record_cloud_activity("system", "Workspace settings updated")
            self._restart_integrations()

    def _adapters(self) -> dict[str, Any]:
        built = {}
        for name, adapter_class in ADAPTERS.items():
            if getattr(adapter_class, "is_scaffold", False):
                if self.database.get_credentials(name):
                    self._log(f"{PLATFORM_TITLES[name]} credentials saved; regional API integration remains scaffolded")
                continue
            credentials = self.database.get_credentials(name)
            if not credentials:
                continue
            try:
                built[name] = adapter_class(credentials)
            except Exception as exc:
                self._log(f"{PLATFORM_TITLES[name]} setup incomplete: {exc}")
        return built

    def _start_integrations(self) -> None:
        config = self.database.get_credentials("general")
        adapters = self._adapters()
        self.platform_metric.value_label.setText(str(len(adapters)))  # type: ignore[attr-defined]
        self.platform_metric.detail_label.setText(
            ", ".join(PLATFORM_TITLES[name] for name in adapters) or "No connected marketplaces"  # type: ignore[attr-defined]
        )
        try:
            poll_seconds = int(config.get("poll_seconds") or 180)
            port = int(config.get("webhook_port") or 8787)
        except (TypeError, ValueError):
            poll_seconds, port = 180, 8787
        self.integration_service = OrderIntegrations(
            self.database, adapters, self._log,
            formatter=self._format_order,
            port=port, poll_seconds=max(30, min(poll_seconds, 3600)),
            enable_webhooks=bool(config.get("enable_webhooks", True)),
        )
        self.integration_service.start()
        self._refresh_orders()

    def _restart_integrations(self) -> None:
        if self.integration_service:
            self.integration_service.stop()
            self.integration_service = None
        self._start_integrations()

    def _format_order(self, order: dict[str, Any], platform: str) -> str:
        try:
            return GeminiAgent(self.database, self._log).format_order_report(order, platform)
        except Exception as exc:
            self._log(f"Order report formatting used standard template: {exc}")
            from .services.channels import whatsapp_summary
            return whatsapp_summary(order, platform)

    def _refresh_orders(self) -> None:
        entries = self.database.recent_orders(25)
        self.orders.setRowCount(len(entries))
        chart_values = []
        for index, entry in enumerate(entries):
            order = entry["data"]
            values = [PLATFORM_TITLES.get(entry["platform"], entry["platform"].title()),
                      str(order.get("name") or order.get("order_number") or entry["external_id"]),
                      f"{order.get('currency', '')} {order.get('total_price') or order.get('total') or '—'}",
                      str(order.get("financial_status") or order.get("status") or "received")]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setForeground(QColor("#d9e6fa"))
                self.orders.setItem(index, column, cell)
            try:
                chart_values.append(float(order.get("total_price") or order.get("total") or 0))
            except (TypeError, ValueError):
                chart_values.append(0)
        self.order_metric.value_label.setText(str(len(entries)))  # type: ignore[attr-defined]
        self.chart.clear()
        if chart_values:
            self.chart.plot(list(range(len(chart_values))), chart_values, pen=pg.mkPen("#22d3c5", width=2),
                            symbol="o", symbolSize=7, symbolBrush="#68f0df")
        self.chart.setLabel("left", "Order total")
        self.chart.setLabel("bottom", "Recent orders")
        self._paint_cloud_analytics()

    def _targets_from_prompt(self, prompt: str) -> list[str]:
        normalized = prompt.lower()
        configured = [name for name in PLATFORMS if self.database.get_credentials(name)]
        matched = []
        aliases = {"shopify": ["shopify"], "daraz": ["daraz"], "amazon": ["amazon"],
                   "ebay": ["ebay", "e-bay"], "woocommerce": ["woocommerce", "woo commerce"],
                   "tiktok_shop": ["tiktok", "tik tok"]}
        for platform in configured:
            if any(alias in normalized for alias in aliases[platform]):
                matched.append(platform)
        if re.search(r"all platforms|all stores|every platform|every store", normalized):
            return configured
        return matched or configured

    def _submit_command(self) -> None:
        prompt = self.command.text().strip()
        if not prompt or self._busy:
            return
        sheet_match = SHEETS_RE.search(prompt)
        if sheet_match:
            url = prompt[sheet_match.start():].split()[0].rstrip(".,)")
            self._begin_bulk(url, self._targets_from_prompt(prompt))
            self.command.clear()
            return
        self.command.clear()
        self._run_agent(prompt)

    def _run_agent(self, prompt: str) -> None:
        self._log(f"You: {prompt}")
        self._busy = True
        self.status_metric.value_label.setText("THINKING")  # type: ignore[attr-defined]
        self.send.setEnabled(False)
        self.worker = WorkThread(self.database, prompt=prompt)
        self.worker.log.connect(self._log)
        self.worker.done.connect(self._work_done)
        self.worker.failed.connect(self._work_failed)
        self.worker.start()

    def _begin_bulk(self, source: str, targets: list[str]) -> None:
        if not targets:
            QMessageBox.information(self, "No connected stores", "Configure a marketplace in Settings before importing products.")
            return
        self._log(f"Bulk import started: {source} → {', '.join(targets)}")
        self._busy = True
        self.send.setEnabled(False)
        self.progress.show()
        self.progress.setValue(0)
        self.worker = WorkThread(self.database, bulk_source=source, targets=targets)
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._bulk_progress)
        self.worker.done.connect(self._work_done)
        self.worker.failed.connect(self._work_failed)
        self.worker.start()

    def _bulk_progress(self, current: int, total: int, message: str) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        self._log(message)

    def _finish_work(self) -> None:
        self._busy = False
        self.send.setEnabled(True)
        self.progress.hide()
        self.status_metric.value_label.setText("READY")  # type: ignore[attr-defined]
        self._refresh_orders()

    def _work_done(self, message: str) -> None:
        self._finish_work()
        try:
            result = json.loads(message)
        except (TypeError, ValueError):
            result = None
        if isinstance(result, dict) and "succeeded" in result and "failed" in result:
            self._log(f"Bulk import complete: {result.get('succeeded')} platform listings succeeded; "
                      f"{result.get('failed')} failed across {result.get('rows')} rows.")
            self._record_cloud_activity(
                "bulk", f"Bulk processing complete · {int(result.get('succeeded') or 0)} succeeded · "
                f"{int(result.get('failed') or 0)} failed"
            )
            failures = [item for item in result.get("results", []) if not item.get("ok")]
            for item in failures[:8]:
                self._log(f"Row {item.get('row')} · {item.get('platform')}: {item.get('error')}")
            if len(failures) > 8:
                self._log(f"And {len(failures) - 8} more platform failures")
            return
        self._log(f"OmniStore: {message}")
        self._record_cloud_activity("ai", "AI command completed")

    def _work_failed(self, message: str) -> None:
        self._finish_work()
        self._log(f"Action failed: {message}")
        self._record_cloud_activity("ai", "AI action needs attention")
        QMessageBox.warning(self, "Action needs attention", message)

    def _voice_command(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.mic.setEnabled(False)
        self.status_metric.value_label.setText("LISTENING")  # type: ignore[attr-defined]
        self._log("Listening for a voice command")
        self.voice = VoiceThread()
        self.voice.transcript.connect(self._voice_result)
        self.voice.failed.connect(self._voice_failed)
        self.voice.start()

    def _voice_result(self, transcript: str) -> None:
        self._busy = False
        self.mic.setEnabled(True)
        self.status_metric.value_label.setText("READY")  # type: ignore[attr-defined]
        self.command.setText(transcript)
        self._log(f"Voice transcription: {transcript}")
        self._submit_command()

    def _voice_failed(self, message: str) -> None:
        self._busy = False
        self.mic.setEnabled(True)
        self.status_metric.value_label.setText("READY")  # type: ignore[attr-defined]
        self._log(message)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt override
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        files = [path for path in paths if path.suffix.lower() in (".xlsx", ".csv", ".docx")]
        if not files:
            self._log("Drop a supported .xlsx, .csv, or .docx file")
            return
        configured = [name for name in PLATFORMS if self.database.get_credentials(name)]
        if not configured:
            QMessageBox.information(self, "Connect a store", "Configure a marketplace in Settings first.")
            return
        dialog = TargetDialog(configured, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            targets = dialog.selection()
            if targets:
                self._begin_bulk(str(files[0]), targets)
        event.acceptProposedAction()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 54:
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if self._drag_position and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        self._drag_position = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if hasattr(self, "cloud_worker") and self.cloud_worker.isRunning():
            event.ignore()
            if not self._cloud_close_requested:
                self._cloud_close_requested = True
                self.setEnabled(False)
                self.cloud_worker.finished.connect(self.close)
                self.cloud_worker.request_stop()
            return
        if self.integration_service:
            self.integration_service.stop()
        if hasattr(self, "worker") and self.worker.isRunning():
            self.worker.wait(2000)
        event.accept()


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("OmniStore AI Manager")
    try:
        window = OmniStoreWindow()
    except Exception as exc:
        QMessageBox.critical(None, "Secure storage unavailable", str(exc))
        return 2
    window.show()
    return app.exec()
