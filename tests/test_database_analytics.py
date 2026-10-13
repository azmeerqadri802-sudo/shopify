from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from omnistore.database import SecureDatabase
    DATABASE_IMPORT_ERROR = ""
except ModuleNotFoundError as exc:
    if exc.name not in {"keyring", "cryptography", "platformdirs"}:
        raise
    SecureDatabase = None  # type: ignore[assignment,misc]
    DATABASE_IMPORT_ERROR = f"runtime dependency {exc.name} is not installed"


class LocalAnalyticsTests(unittest.TestCase):
    @unittest.skipIf(SecureDatabase is None, DATABASE_IMPORT_ERROR)
    def test_orders_are_deduplicated_and_aggregated_by_day_and_currency(self) -> None:
        key_store: dict[tuple[str, str], str] = {}

        def get_password(service: str, account: str) -> str | None:
            return key_store.get((service, account))

        def set_password(service: str, account: str, value: str) -> None:
            key_store[(service, account)] = value

        with tempfile.TemporaryDirectory() as temp_dir, \
                patch("keyring.get_password", side_effect=get_password), \
                patch("keyring.set_password", side_effect=set_password):
            database = SecureDatabase(Path(temp_dir) / "test.sqlite3")
            self.assertTrue(database.insert_order_if_new("shopify", "1", {
                "total_price": "12.34", "currency": "usd", "email": "private@example.com"
            }))
            self.assertTrue(database.insert_order_if_new("shopify", "2", {
                "total_price": "7.66", "currency": "USD"
            }))
            self.assertFalse(database.insert_order_if_new("shopify", "2", {
                "total_price": "7.66", "currency": "USD"
            }))
            rows = database.daily_sales(2)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["orders_count"], 2)
            self.assertEqual(rows[0]["gross_sales"], 20.0)
            self.assertNotIn("private@example.com", str(rows))


if __name__ == "__main__":
    unittest.main()
