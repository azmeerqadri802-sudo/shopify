"""Shopify Admin REST adapter (online-store URL and custom-app token)."""

from __future__ import annotations

from typing import Any

from .base import AdapterError, PlatformAdapter
from ..models import UniversalProduct


class ShopifyAdapter(PlatformAdapter):
    platform = "shopify"

    def __init__(self, credentials: dict[str, Any]) -> None:
        super().__init__(credentials)
        self.store_url = str(credentials.get("store_url", "")).strip().rstrip("/")
        token = str(credentials.get("admin_token", "")).strip()
        if not self.store_url.startswith("https://") or not token:
            raise AdapterError("Shopify needs an https:// store URL and Admin API token")
        self.api_version = str(credentials.get("api_version") or "2025-10")
        self.session.headers.update({"X-Shopify-Access-Token": token, "Content-Type": "application/json"})
        self.base = f"{self.store_url}/admin/api/{self.api_version}"

    def create_product(self, product: UniversalProduct) -> dict[str, Any]:
        payload = {
            "product": {
                "title": product.title,
                "body_html": product.description,
                "vendor": product.vendor or "OmniStore",
                "product_type": product.product_type,
                "tags": ", ".join(product.tags),
                "status": "draft",
                "variants": [{"price": str(product.price), "sku": product.sku,
                              "inventory_management": "shopify", "inventory_quantity": product.inventory_quantity}],
                "images": [{"src": url} for url in product.image_urls],
            }
        }
        result = self.check(self.session.post(f"{self.base}/products.json", json=payload, timeout=30))
        if "product" not in result:
            raise AdapterError("Shopify response did not contain a product")
        return result["product"]

    def fetch_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        params = {"status": "any", "limit": min(int(kwargs.get("limit", 50)), 250),
                  "created_at_min": kwargs.get("created_at_min")}
        result = self.check(self.session.get(f"{self.base}/orders.json", params=params, timeout=30))
        return result.get("orders", [])

    def update_inventory(self, product_id: str, quantity: int, **kwargs: Any) -> dict[str, Any]:
        inventory_item_id = str(kwargs.get("inventory_item_id") or "")
        location_id = str(kwargs.get("location_id") or "")
        if not inventory_item_id or not location_id:
            raise AdapterError("Shopify inventory updates need inventory_item_id and location_id")
        return self.check(self.session.post(
            f"{self.base}/inventory_levels/set.json",
            json={"inventory_item_id": inventory_item_id, "location_id": location_id,
                  "available": max(0, int(quantity))}, timeout=30))
