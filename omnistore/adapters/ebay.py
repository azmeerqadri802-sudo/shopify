"""eBay Sell Inventory and Fulfillment REST adapter."""

from __future__ import annotations

import re
from typing import Any

from .base import AdapterError, PlatformAdapter
from ..models import UniversalProduct


class EbayAdapter(PlatformAdapter):
    platform = "ebay"
    api_base = "https://api.ebay.com"

    def __init__(self, credentials: dict[str, Any]) -> None:
        super().__init__(credentials)
        token = str(credentials.get("access_token", "")).strip()
        if not token:
            raise AdapterError("eBay needs a valid OAuth user access token")
        self.c = credentials
        self.session.headers.update({"Authorization": f"Bearer {token}",
                                     "Content-Type": "application/json", "Content-Language": "en-US"})

    @staticmethod
    def _sku(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]", "-", value).strip("-")
        return (safe or "OMNI-PRODUCT")[:50]

    def create_product(self, product: UniversalProduct) -> dict[str, Any]:
        sku = self._sku(product.sku or product.title)
        inventory = {
            "availability": {"shipToLocationAvailability": {"quantity": product.inventory_quantity}},
            "condition": str(self.c.get("condition") or "NEW"),
            "product": {"title": product.title, "description": product.description,
                        "imageUrls": product.image_urls, "aspects": {"Brand": [product.vendor or "Generic"]}},
        }
        self.check(self.session.put(f"{self.api_base}/sell/inventory/v1/inventory_item/{sku}",
                                    json=inventory, timeout=30))
        offer_body = {
            "sku": sku, "marketplaceId": self.c.get("marketplace_id", "EBAY_US"),
            "format": "FIXED_PRICE", "availableQuantity": product.inventory_quantity,
            "categoryId": self.c.get("category_id"), "merchantLocationKey": self.c.get("location_key"),
            "listingDescription": product.description,
            "pricingSummary": {"price": {"value": str(product.price), "currency": product.currency}},
            "listingPolicies": {"fulfillmentPolicyId": self.c.get("fulfillment_policy_id"),
                                "paymentPolicyId": self.c.get("payment_policy_id"),
                                "returnPolicyId": self.c.get("return_policy_id")},
        }
        missing = [key for key in ("categoryId", "merchantLocationKey") if not offer_body.get(key)]
        if missing:
            raise AdapterError("eBay inventory item saved but is not listed; configure category ID and location key")
        offer = self.check(self.session.post(f"{self.api_base}/sell/inventory/v1/offer",
                                             json=offer_body, timeout=30))
        offer_id = offer.get("offerId")
        if not offer_id:
            raise AdapterError(f"eBay did not return an offer ID: {offer}")
        published = self.check(self.session.post(f"{self.api_base}/sell/inventory/v1/offer/{offer_id}/publish",
                                                 timeout=30))
        return {"sku": sku, "offer": offer, "publication": published}

    def fetch_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        params = {"limit": min(int(kwargs.get("limit", 50)), 200)}
        if kwargs.get("created_after"):
            params["filter"] = f"creationdate:[{kwargs['created_after']}..]"
        result = self.check(self.session.get(f"{self.api_base}/sell/fulfillment/v1/order",
                                             params=params, timeout=30))
        return result.get("orders", [])

    def update_inventory(self, product_id: str, quantity: int, **kwargs: Any) -> dict[str, Any]:
        sku = self._sku(str(kwargs.get("sku") or product_id))
        return self.check(self.session.put(f"{self.api_base}/sell/inventory/v1/inventory_item/{sku}",
                                           json={"availability": {"shipToLocationAvailability": {
                                               "quantity": max(0, int(quantity))}}}, timeout=30))
