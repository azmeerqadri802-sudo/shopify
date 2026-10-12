# Settings storage. Secrets stay in the operating system credential manager.

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import keyring
from platformdirs import user_config_path


APP_NAME = "ShopifyAIStoreManager"
SERVICE_NAME = "ShopifyAIStoreManager"
CONFIG_DIR = Path(user_config_path(APP_NAME, appauthor=False))
CONFIG_FILE = CONFIG_DIR / "settings.json"


@dataclass
class AppConfig:
    store_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_from_email: str = ""
    gemini_model: str = "gemini-3.8-flash"
    shopify_api_version: str = "2026-10"
    whatsapp_graph_api_version: str = "v23.0"
    whatsapp_phone_number_id: str = ""
    whatsapp_template_name: str = ""
    whatsapp_template_language: str = "en_US"
    require_confirmation: bool = True


SECRET_KEYS = (
    "gemini_api_key",
    "shopify_admin_api_token",
    "smtp_username",
    "smtp_password",
    "whatsapp_cloud_api_token",
    "whatsapp_number",
)


class SettingsStore:
    """Persist non-secret preferences as JSON and secrets through OS keyring."""

    def load(self) -> AppConfig:
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            allowed = AppConfig.__dataclass_fields__.keys()
            return AppConfig(**{key: value for key, value in raw.items() if key in allowed})
        except FileNotFoundError:
            return AppConfig()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # Keep a damaged preferences file from preventing the app from opening.
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(config), indent=2, ensure_ascii=False)
        fd, temporary_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=CONFIG_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, CONFIG_FILE)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass

    def get_secret(self, key: str) -> str:
        self._validate_secret_key(key)
        return keyring.get_password(SERVICE_NAME, key) or ""

    def set_secret(self, key: str, value: str) -> None:
        self._validate_secret_key(key)
        if value:
            keyring.set_password(SERVICE_NAME, key, value)

    @staticmethod
    def _validate_secret_key(key: str) -> None:
        if key not in SECRET_KEYS:
            raise ValueError("Unknown secret name")

    def secret_is_configured(self, key: str) -> bool:
        return bool(self.get_secret(key))

