"""Shopify Admin GraphQL client and bounded store data snapshots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlparse

import requests

from .config import AppConfig


class ShopifyError(RuntimeError):
    """Safe Shopify integration error."""


@dataclass(slots=True)
class ShopifyData:
    recent_orders: list[dict]
    daily_sales: dict[str, float]
    currency: str
    variants: list[dict]
    units_sold_by_variant: dict[str, int]
    lookback_days: int


class ShopifyClient:
    def __init__(self, config: AppConfig, access_token: str) -> None:
        if not access_token:
            raise ShopifyError("Add a Shopify Admin API token in Settings.")
        parsed = urlparse(config.store_url.strip())
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not (host.endswith(".myshopify.com") or host == "myshopify.com")
            or parsed.username or parsed.password or parsed.port
        ):
            raise ShopifyError(
                "Use a secure Shopify domain such as https://your-store.myshopify.com."
            )
        version = config.shopify_api_version.strip()
        if not re.fullmatch(r"\d{4}-(01|04|07|10)", version):
            raise ShopifyError("Shopify API version should look like 2026-10.")
        self.endpoint = f"https://{host}/admin/api/{version}/graphql.json"
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "ShopifyAIManager/2.0",
            "X-Shopify-Access-Token": access_token,
        })

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        try:
            response = self.session.post(
                self.endpoint,
                json={"query": query, "variables": variables or {}},
                timeout=(10, 45),
            )
        except requests.RequestException as exc:
            raise ShopifyError("Could not reach Shopify. Check the network and store URL.") from exc
        if not response.ok:
            raise ShopifyError(f"Shopify returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ShopifyError("Shopify returned an invalid response.") from exc
        if payload.get("errors"):
            messages = [
                str(item.get("message", "GraphQL error"))
                for item in payload["errors"] if isinstance(item, dict)
            ]
            raise ShopifyError("; ".join(messages)[:700] or "Shopify GraphQL failed.")
        return payload.get("data") or {}

    def recent_orders(self, limit: int = 12) -> list[dict]:
        query = """
        query RecentOrders($first: Int!) {
          orders(first: $first, sortKey: CREATED_AT, reverse: true) {
            nodes {
              id name createdAt displayFinancialStatus
              currentTotalPriceSet { shopMoney { amount currencyCode } }
              customer { displayName }
            }
          }
        }
        """
        data = self.graphql(query, {"first": max(1, min(limit, 50))})
        orders = []
        for item in (data.get("orders") or {}).get("nodes") or []:
            money = (item.get("currentTotalPriceSet") or {}).get("shopMoney") or {}
            orders.append({
                "name": item.get("name") or "Order",
                "created_at": item.get("createdAt") or "",
                "customer": (item.get("customer") or {}).get("displayName") or "Guest",
                "total": money.get("amount") or "0.00",
                "currency": money.get("currencyCode") or "",
                "status": item.get("displayFinancialStatus") or "UNKNOWN",
            })
        return orders

    def analytics(self, lookback_days: int = 90, max_pages: int = 8) -> ShopifyData:
        days = max(7, min(int(lookback_days), 365))
        since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
        query = """
        query SalesHistory($first: Int!, $after: String, $filter: String!) {
          orders(first: $first, after: $after, query: $filter,
                 sortKey: CREATED_AT, reverse: false) {
            edges {
              cursor
              node {
                createdAt
                currentTotalPriceSet { shopMoney { amount currencyCode } }
                lineItems(first: 20) {
                  nodes { quantity variant { id product { title } } }
                }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        daily: defaultdict[str, float] = defaultdict(float)
        units: defaultdict[str, int] = defaultdict(int)
        currency = ""
        cursor = None
        for _ in range(max(1, min(max_pages, 12))):
            data = self.graphql(query, {
                "first": 40,
                "after": cursor,
                "filter": f"created_at:>={since}",
            })
            connection = data.get("orders") or {}
            for edge in connection.get("edges") or []:
                order = edge.get("node") or {}
                created = str(order.get("createdAt") or "")
                if created:
                    try:
                        day = datetime.fromisoformat(created.replace("Z", "+00:00")).date().isoformat()
                    except ValueError:
                        day = created[:10]
                    money = ((order.get("currentTotalPriceSet") or {}).get("shopMoney") or {})
                    currency = currency or str(money.get("currencyCode") or "")
                    try:
                        daily[day] += float(Decimal(str(money.get("amount") or "0")))
                    except (InvalidOperation, ValueError):
                        pass
                for line in (order.get("lineItems") or {}).get("nodes") or []:
                    variant = line.get("variant") or {}
                    if variant.get("id"):
                        try:
                            units[str(variant["id"])] += max(0, int(line.get("quantity") or 0))
                        except (TypeError, ValueError):
                            continue
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage") or not page.get("endCursor"):
                break
            cursor = page["endCursor"]

        products_query = """
        query InventorySnapshot($first: Int!, $after: String!) {
          products(first: $first, after: $after, sortKey: TITLE) {
            edges {
              cursor
              node {
                title
                variants(first: 20) {
                  nodes { id title inventoryQuantity inventoryItem { tracked } }
                }
              }
            }
            pageInfo { hasNextPage endCursor }
          }
        }
        """
        variants: list[dict] = []
        product_cursor = ""
        for _ in range(6):
            data = self.graphql(products_query, {"first": 30, "after": product_cursor})
            connection = data.get("products") or {}
            for edge in connection.get("edges") or []:
                product = edge.get("node") or {}
                for variant in (product.get("variants") or {}).get("nodes") or []:
                    variants.append({
                        "id": str(variant.get("id") or ""),
                        "product": str(product.get("title") or "Product"),
                        "variant": str(variant.get("title") or "Default"),
                        "available": variant.get("inventoryQuantity"),
                        "tracked": bool((variant.get("inventoryItem") or {}).get("tracked")),
                    })
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage") or not page.get("endCursor"):
                break
            product_cursor = page["endCursor"]
        return ShopifyData(
            recent_orders=self.recent_orders(),
            daily_sales=dict(daily),
            currency=currency,
            variants=variants,
            units_sold_by_variant=dict(units),
            lookback_days=days,
        )

    def create_draft_product(
        self, *, title: str, image_url: str, price: float, description_html: str,
        seo_title: str, seo_description: str, tags: list[str],
    ) -> dict:
        try:
            amount = Decimal(str(price)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise ShopifyError("Enter a valid product price.") from exc
        if not amount.is_finite() or amount <= 0 or amount > Decimal("100000000"):
            raise ShopifyError("Product price must be a positive supported amount.")
        title = title.strip()
        if not title or len(title) > 255:
            raise ShopifyError("Product title must contain 1 to 255 characters.")
        media = []
        if image_url.strip():
            parsed = urlparse(image_url.strip())
            if parsed.scheme != "https" or not parsed.netloc:
                raise ShopifyError("Product image URL must use HTTPS.")
            media = [{
                "originalSource": image_url.strip(),
                "mediaContentType": "IMAGE",
                "alt": title[:255],
            }]
        mutation = """
        mutation CreateDraft($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
          productCreate(product: $product, media: $media) {
            product { id title variants(first: 1) { nodes { id } } }
            userErrors { field message }
          }
        }
        """
        data = self.graphql(mutation, {
            "product": {
                "title": title,
                "descriptionHtml": description_html,
                "status": "DRAFT",
                "seo": {"title": seo_title[:70], "description": seo_description[:320]},
                "tags": tags[:20],
            },
            "media": media,
        })
        result = data.get("productCreate") or {}
        errors = result.get("userErrors") or []
        if errors:
            raise ShopifyError("; ".join(str(row.get("message", "Product failed")) for row in errors)[:600])
        product = result.get("product") or {}
        variants = (product.get("variants") or {}).get("nodes") or []
        if not product.get("id") or not variants:
            raise ShopifyError("Shopify did not return the new draft product variant.")
        price_mutation = """
        mutation SetDraftPrice($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            userErrors { field message }
          }
        }
        """
        priced = self.graphql(price_mutation, {
            "productId": product["id"],
            "variants": [{"id": variants[0]["id"], "price": str(amount)}],
        }).get("productVariantsBulkUpdate") or {}
        errors = priced.get("userErrors") or []
        if errors:
            raise ShopifyError(
                "Product draft was created, but its price could not be set: "
                + "; ".join(str(row.get("message", "Price update failed")) for row in errors)[:500]
            )
        return {"id": product["id"], "title": product.get("title") or title,
                "price": str(amount), "status": "DRAFT"}

