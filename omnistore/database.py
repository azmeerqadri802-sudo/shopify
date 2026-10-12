"""Encrypted credential and order persistence using SQLite + OS keychain."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import keyring
from cryptography.fernet import Fernet, InvalidToken
from platformdirs import user_data_dir

LOG = logging.getLogger(__name__)
KEYRING_SERVICE = "OmniStoreAIManager"
KEYRING_ACCOUNT = "sqlite-encryption-key"


class SecureDatabase:
    """SQLite data store. Secrets and order payloads are Fernet-encrypted.

    The Fernet key is stored by the operating system credential manager, never
    in the database or project directory. The application fails closed if the
    system keychain is unavailable instead of silently writing plaintext.
    """

    def __init__(self, database_path: str | Path | None = None) -> None:
        folder = Path(user_data_dir("OmniStoreAI", "OmniStore"))
        folder.mkdir(parents=True, exist_ok=True)
        self.path = Path(database_path) if database_path else folder / "omni_store.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cipher = self._load_cipher()
        self._initialize()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            LOG.debug("File permission hardening is not supported on this platform")

    @staticmethod
    def _load_cipher() -> Fernet:
        try:
            key = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
            if not key:
                key = Fernet.generate_key().decode("ascii")
                keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, key)
                if keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT) != key:
                    raise RuntimeError("Operating system keychain did not retain the database key")
            return Fernet(key.encode("ascii"))
        except Exception as exc:
            raise RuntimeError(
                "Secure storage requires a working Windows Credential Manager or macOS Keychain. "
                "No credentials were saved."
            ) from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS credentials ("
                "service TEXT PRIMARY KEY, ciphertext BLOB NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS orders ("
                "id INTEGER PRIMARY KEY, platform TEXT NOT NULL, external_id TEXT NOT NULL, "
                "ciphertext BLOB NOT NULL, received_at TEXT NOT NULL, "
                "UNIQUE(platform, external_id))"
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_orders_received ON orders(received_at DESC)")

    def save_credentials(self, service: str, credentials: dict[str, Any]) -> None:
        payload = json.dumps(credentials, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ciphertext = self._cipher.encrypt(payload)
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                "INSERT INTO credentials(service,ciphertext,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(service) DO UPDATE SET ciphertext=excluded.ciphertext, "
                "updated_at=excluded.updated_at",
                (service, ciphertext, timestamp),
            )

    def get_credentials(self, service: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT ciphertext FROM credentials WHERE service=?", (service,)).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(self._cipher.decrypt(row["ciphertext"]).decode("utf-8"))
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise RuntimeError(f"Could not decrypt saved credentials for {service}") from exc
        return value if isinstance(value, dict) else {}

    def configured_services(self) -> set[str]:
        with self._connect() as db:
            rows = db.execute("SELECT service FROM credentials").fetchall()
        return {str(row["service"]) for row in rows}

    def insert_order_if_new(self, platform: str, external_id: str, order: dict[str, Any]) -> bool:
        """Save a deduplicated order; return True only for a newly seen order."""
        if not external_id:
            return False
        ciphertext = self._cipher.encrypt(json.dumps(order, ensure_ascii=False, default=str).encode("utf-8"))
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO orders(platform,external_id,ciphertext,received_at) VALUES(?,?,?,?)",
                (platform, str(external_id), ciphertext, timestamp),
            )
            return cursor.rowcount == 1

    def recent_orders(self, limit: int = 25) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as db:
            rows = db.execute(
                "SELECT platform,external_id,ciphertext,received_at FROM orders "
                "ORDER BY received_at DESC LIMIT ?", (limit,)
            ).fetchall()
        output = []
        for row in rows:
            try:
                order = json.loads(self._cipher.decrypt(row["ciphertext"]).decode("utf-8"))
            except (InvalidToken, ValueError, UnicodeError):
                LOG.error("Unable to decrypt stored order %s from %s", row["external_id"], row["platform"])
                continue
            output.append({
                "platform": row["platform"],
                "external_id": row["external_id"],
                "received_at": row["received_at"],
                "data": order if isinstance(order, dict) else {},
            })
        return output
