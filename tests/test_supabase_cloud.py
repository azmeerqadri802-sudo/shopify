from __future__ import annotations

import base64
import json
import unittest
from types import SimpleNamespace

from omnistore.services.supabase_cloud import (
    SupabaseCloudStore,
    SupabaseConfigurationError,
    SupabaseCredentials,
    validate_credentials,
)


def legacy_jwt(role: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


class FakeQuery:
    def __init__(self, table: "FakeTable", operation: str, payload=None) -> None:
        self.table, self.operation, self.payload = table, operation, payload

    def select(self, _columns: str) -> "FakeQuery":
        self.operation = "select"
        return self

    def order(self, _column: str, **_kwargs) -> "FakeQuery":
        return self

    def limit(self, _count: int) -> "FakeQuery":
        return self

    def insert(self, payload) -> "FakeQuery":
        self.operation, self.payload = "insert", payload
        return self

    def upsert(self, payload, **kwargs) -> "FakeQuery":
        self.operation, self.payload = "upsert", (payload, kwargs)
        return self

    def execute(self):
        self.table.calls.append((self.operation, self.payload))
        if self.operation == "select":
            return SimpleNamespace(data=self.table.rows)
        return SimpleNamespace(data=[])


class FakeTable:
    def __init__(self) -> None:
        self.calls = []
        self.rows = []

    def select(self, _columns: str) -> FakeQuery:
        return FakeQuery(self, "select")

    def insert(self, payload) -> FakeQuery:
        return FakeQuery(self, "insert", payload)

    def upsert(self, payload, **kwargs) -> FakeQuery:
        return FakeQuery(self, "upsert", (payload, kwargs))


class FakeClient:
    def __init__(self) -> None:
        self.tables = {"agent_activity": FakeTable(), "daily_analytics": FakeTable()}
        self.signed_out = False
        self.auth = SimpleNamespace(
            sign_in_with_password=lambda _creds: SimpleNamespace(user=SimpleNamespace(id="user-123")),
            sign_out=self._sign_out,
        )

    def _sign_out(self) -> None:
        self.signed_out = True

    def table(self, name: str) -> FakeTable:
        return self.tables[name]


class SupabaseCloudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.credentials = SupabaseCredentials(
            "https://sample.supabase.co", "sb_publishable_example", "owner@example.com", "local-secret"
        )
        self.client = FakeClient()
        self.store = SupabaseCloudStore(self.credentials, lambda *_args: self.client)
        self.store.connect()

    def test_publishable_key_is_accepted_and_secret_keys_are_rejected(self) -> None:
        validate_credentials(self.credentials)
        unsafe = SupabaseCredentials(
            self.credentials.project_url, legacy_jwt("service_role"), self.credentials.email, self.credentials.password
        )
        with self.assertRaises(SupabaseConfigurationError):
            validate_credentials(unsafe)

    def test_activity_is_redacted_and_bound_to_authenticated_user(self) -> None:
        self.store.record_activity("system", "Workspace settings updated for owner@example.com")
        operation, payload = self.client.tables["agent_activity"].calls[0]
        self.assertEqual(operation, "upsert")
        self.assertEqual(payload[0]["user_id"], "user-123")
        self.assertNotIn("owner@example.com", payload[0]["message"])
        self.assertEqual(payload[1]["on_conflict"], "id")

    def test_daily_analytics_upsert_is_per_user_and_has_no_order_payload(self) -> None:
        self.store.upsert_daily_sales([{
            "sales_date": "2026-10-13", "currency": "USD", "orders_count": 3, "gross_sales": 42.5
        }])
        operation, (rows, options) = self.client.tables["daily_analytics"].calls[0]
        self.assertEqual(operation, "upsert")
        self.assertEqual(rows[0]["user_id"], "user-123")
        self.assertEqual(options["on_conflict"], "user_id,sales_date,currency")
        self.assertNotIn("customer", rows[0])

    def test_client_signs_out_when_closed(self) -> None:
        self.store.close()
        self.assertTrue(self.client.signed_out)


if __name__ == "__main__":
    unittest.main()
