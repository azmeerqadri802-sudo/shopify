"""Typed preferences and secure OS credential-store access."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import keyring
from platformdirs import user_config_path

APP_NAME = "ShopifyAIManager"
KEYRING_SERVICE = APP_NAME
CONFIG_DIR = Path(user_config_path(APP_NAME, appauthor=False))
CONFIG_FILE = CONFIG_DIR / "settings.json"
SECRET_NAMES = frozenset({
    "gemini_api_key",
    "shopify_admin_api_token",
    "whatsapp_number",
    "whatsapp_cloud_api_token",
    "smtp_username",
    "smtp_password",
    "tavily_api_key",
})


@dataclass(slots=True)
class AppConfig:
    store_url: str = ""
    shopify_api_version: str = "2026-10"
    gemini_model: str = "gemini-3.8-flash"
    whatsapp_phone_number_id: str = ""
    whatsapp_graph_api_version: str = "v23.0"
    whatsapp_template_name: str = ""
    whatsapp_template_language: str = "en_US"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_from_email: str = ""
    speech_language: str = "en-US"
    require_confirmation: bool = True


class SettingsError(RuntimeError):
    """Safe message for settings and OS-vault failures."""


class SettingsStore:
    """Store preferences in user config and secrets in Credential Manager/Keychain."""

    def load(self) -> AppConfig:
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return AppConfig()
        except (OSError, json.JSONDecodeError) as exc:
            raise SettingsError(f"Could not read settings: {exc}") from exc
        if not isinstance(raw, dict):
            return AppConfig()
        allowed = AppConfig.__dataclass_fields__.keys()
        try:
            return AppConfig(**{key: value for key, value in raw.items() if key in allowed})
        except (TypeError, ValueError) as exc:
            raise SettingsError(f"Settings contain an invalid value: {exc}") from exc

    def get_secret(self, name: str) -> str:
        self._validate_name(name)
        try:
            return keyring.get_password(KEYRING_SERVICE, name) or ""
        except Exception as exc:
            raise SettingsError(
                "The operating-system credential vault is unavailable. "
                "No plaintext fallback is used."
            ) from exc

    def save(self, config: AppConfig, secrets: dict[str, str]) -> None:
        for name in secrets:
            self._validate_name(name)
        try:
            for name, value in secrets.items():
                if value:
                    keyring.set_password(KEYRING_SERVICE, name, value)
        except Exception as exc:
            raise SettingsError(
                "Could not save credentials to the OS vault. Check Credential Manager or Keychain."
            ) from exc

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=CONFIG_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(asdict(config), handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, CONFIG_FILE)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _validate_name(name: str) -> None:
        if name not in SECRET_NAMES:
            raise SettingsError("Unknown credential name.")

