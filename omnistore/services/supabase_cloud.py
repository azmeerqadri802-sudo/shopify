"""Authenticated, user-scoped Supabase access for cloud activity and analytics.

This module deliberately imports the Supabase SDK only when a connection is
opened. The desktop UI can therefore start cleanly before optional cloud
dependencies/configuration are available, and credentials stay in the local
OS-keychain-encrypted SQLite store.
"""

from __future__ import annotations

import base64
import ipaddress
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit


class SupabaseConfigurationError(ValueError):
    """Raised when the local Supabase connection settings are unsafe/invalid."""


@dataclass(frozen=True)
class SupabaseCredentials:
    project_url: str
    publishable_key: str
    email: str
    password: str

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "SupabaseCredentials":
        credentials = cls(
            project_url=str(values.get("project_url") or "").strip().rstrip("/"),
            publishable_key=str(values.get("publishable_key") or "").strip(),
            email=str(values.get("email") or "").strip(),
            password=str(values.get("password") or ""),
        )
        validate_credentials(credentials)
        return credentials


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _jwt_role(key: str) -> str | None:
    """Read a legacy JWT role without treating the unverified claim as trusted."""
    parts = key.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        import json

        role = json.loads(base64.urlsafe_b64decode(payload.encode("ascii"))).get("role")
    except (ValueError, UnicodeError, AttributeError):
        return None
    return str(role).lower() if role else None


def validate_credentials(credentials: SupabaseCredentials) -> None:
    try:
        parsed = urlsplit(credentials.project_url)
        _ = parsed.port
    except ValueError as exc:
        raise SupabaseConfigurationError("Enter a valid Supabase project URL.") from exc
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise SupabaseConfigurationError("Enter a valid Supabase project URL (https://<project>.supabase.co).")
    if parsed.scheme != "https" and not _is_loopback(parsed.hostname):
        raise SupabaseConfigurationError("Supabase connections must use HTTPS (HTTP is allowed only for localhost).")
    if not credentials.publishable_key:
        raise SupabaseConfigurationError("Enter a Supabase publishable key (or legacy anon key).")
    key = credentials.publishable_key
    role = _jwt_role(key)
    if key.startswith("sb_secret_") or role == "service_role":
        raise SupabaseConfigurationError(
            "A Supabase secret/service-role key is not allowed in a desktop app. Use the publishable/anon key."
        )
    if not (key.startswith("sb_publishable_") or role == "anon"):
        raise SupabaseConfigurationError("The API key must be a Supabase publishable key or a legacy anon JWT.")
    if not credentials.email or "@" not in credentials.email:
        raise SupabaseConfigurationError("Enter the email address of an existing Supabase Auth user.")
    if not credentials.password:
        raise SupabaseConfigurationError("Enter the Supabase Auth password. It is encrypted in local storage.")


def sanitize_activity_message(message: str) -> str:
    """Redact common identifiers before an allowlisted event reaches the cloud."""
    value = str(message).replace("\x00", " ").strip()
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", value)
    value = re.sub(r"(?i)bearer\s+\S+", "Bearer [redacted]", value)
    value = re.sub(r"\b(?:sk|pk|shpat|shpca|shppa|shpss|gh[pousr]s|sb_secret)_[A-Za-z0-9_-]{8,}\b",
                   "[secret]", value)
    value = re.sub(r"https?://\S+", "[url]", value)
    value = re.sub(r"(?:[A-Za-z]:\\|/)(?:[^\s\\/]+[\\/])+[^\s]*", "[path]", value)
    value = re.sub(r"\+?\d[\d ()-]{7,}\d", "[phone]", value)
    value = " ".join(value.split())
    return value[:300]


class SupabaseCloudStore:
    """Supabase SDK facade. Instantiate/use/dispose it from one worker thread."""

    def __init__(self, credentials: SupabaseCredentials,
                 client_factory: Callable[..., Any] | None = None) -> None:
        self.credentials = credentials
        self._client_factory = client_factory
        self.client: Any | None = None
        self.user_id: str | None = None

    def connect(self) -> None:
        try:
            if self._client_factory is None:
                from supabase import create_client

                factory = create_client
            else:
                factory = self._client_factory
            client = factory(self.credentials.project_url, self.credentials.publishable_key)
            response = client.auth.sign_in_with_password({
                "email": self.credentials.email,
                "password": self.credentials.password,
            })
            user = getattr(response, "user", None)
            user_id = getattr(user, "id", None)
            if not user_id:
                raise RuntimeError("Supabase Auth did not return an authenticated user")
        except ImportError as exc:
            raise RuntimeError("The Supabase SDK is missing. Reinstall the app dependencies.") from exc
        except Exception as exc:
            # Do not bubble SDK request bodies or headers into UI logs.
            raise RuntimeError("Supabase sign-in failed. Check the project URL, public key, and Auth credentials.") from exc
        self.client = client
        self.user_id = str(user_id)

    def record_activity(self, event_type: str, message: str, event_id: str | None = None) -> None:
        if event_type not in {"system", "ai", "bulk"}:
            raise ValueError("Unsupported cloud activity type")
        safe_message = sanitize_activity_message(message)
        if not safe_message:
            return
        client, user_id = self._authenticated()
        client.table("agent_activity").upsert({
            "id": event_id or str(uuid.uuid4()),
            "user_id": user_id,
            "event_type": event_type,
            "message": safe_message,
        }, on_conflict="id").execute()

    def upsert_daily_sales(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        client, user_id = self._authenticated()
        payload = []
        for row in rows:
            payload.append({
                "user_id": user_id,
                "sales_date": str(row["sales_date"]),
                "currency": str(row.get("currency") or "UNK")[:8].upper(),
                "orders_count": max(0, int(row.get("orders_count") or 0)),
                "gross_sales": round(float(row.get("gross_sales") or 0), 2),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        client.table("daily_analytics").upsert(
            payload, on_conflict="user_id,sales_date,currency"
        ).execute()

    def fetch_snapshot(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        client, _ = self._authenticated()
        activities = client.table("agent_activity").select(
            "id,event_type,message,created_at"
        ).order("created_at", desc=True).limit(80).execute().data or []
        analytics = client.table("daily_analytics").select(
            "sales_date,currency,orders_count,gross_sales,updated_at"
        ).order("sales_date", desc=True).limit(1000).execute().data or []
        return list(activities), list(analytics)

    def close(self) -> None:
        """End the authenticated SDK session when its worker shuts down."""
        client, self.client = self.client, None
        self.user_id = None
        if client is not None:
            try:
                client.auth.sign_out()
            except Exception:
                # A session is local to this client instance; server sign-out is best effort.
                pass

    def _authenticated(self) -> tuple[Any, str]:
        if self.client is None or self.user_id is None:
            raise RuntimeError("Supabase client is not authenticated")
        return self.client, self.user_id
