"""WooCommerce REST API adapter."""

from __future__ import annotations

from typing import Any

from .base import AdapterError, PlatformAdapter
from ..models import UniversalProduct


class WooCommerceAdapter(PlatformAdapter):
    platform = "woocommerce"

    def __init__(self, credentials: dict[str, Any]) -> None:
        super().__init__(credentials)
        self.base_url = str(credentials.get("store_url", "")).strip().rstrip("/")
        key = str(credentials.get("consumer_key", "")).strip()
        secret = str(credentials.get("consumer_secret", "")).strip()
        if not self.base_url.startswith("https://") or not key or not secret:
            raise AdapterError("WooCommerce needs an https:// URL, consumer key, and consumer secret")
        self.api_base = f"{self.base_url}/wp-json/wc/v3"
        self.auth = (key, secret)

    def create_product(self, product: UniversalProduct) -> dict[str, Any]:
        payload = {
            "name": product.title, "type": "simple", "status": "draft",
            "description": product.description, "sku": product.sku,
            "regular_price": str(product.price), "manage_stock": True,
            "stock_quantity": product.inventory_quantity,
            "categories": [], "tags": [{"name": tag} for tag in product.tags],
            "images": [{"src": url} for url in product.image_urls],
        }
        return self.check(self.session.post(f"{self.api_base}/products", auth=self.auth,
                                            json=payload, timeout=30))

    def fetch_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        result = self.check(self.session.get(f"{self.api_base}/orders", auth=self.auth,
                                             params={"per_page": min(int(kwargs.get("limit", 50)), 100),
                                                     "after": kwargs.get("after")}, timeout=30))
        return result if isinstance(result, list) else result.get("data", [])

    def update_inventory(self, product_id: str, quantity: int, **kwargs: Any) -> dict[str, Any]:
        return self.check(self.session.put(f"{self.api_base}/products/{product_id}", auth=self.auth,
                                           json={"manage_stock": True, "stock_quantity": max(0, int(quantity))},
                                           timeout=30))
