# Small Shopify Admin GraphQL client with bounded requests and validation.

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests

from .config import AppConfig


class ShopifyError(RuntimeError):
    pass


@dataclass
class OrderSummary:
    name: str
    created_at: str
    customer: str
    total: str
    currency: str
    financial_status: str


class ShopifyClient:
    def __init__(self, config: AppConfig, access_token: str) -> None:
        if not access_token:
            raise ShopifyError("Save a Shopify Admin API token in Settings first.")
        parsed = urlparse(config.store_url.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (host.endswith(".myshopify.com") or host == "myshopify.com"):
            raise ShopifyError("Use a Shopify store URL like https://your-store.myshopify.com.")
        if parsed.username or parsed.password or parsed.port:
            raise ShopifyError("The Shopify store URL must not contain credentials or a custom port.")
        version = config.shopify_api_version.strip()
        if not version or any(ch not in "0123456789-" for ch in version):
            raise ShopifyError("Shopify API version must look like 2026-10.")
        self.url = f"https://{host}/admin/api/{version}/graphql.json"
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Shopify-Access-Token": access_token,
            "User-Agent": "ShopifyAIStoreManager/1.0",
        })

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        try:
            response = self.session.post(
                self.url, json={"query": query, "variables": variables or {}}, timeout=(10, 45)
            )
        except requests.RequestException as exc:
            raise ShopifyError(f"Could not reach Shopify: {exc}") from exc
        if not response.ok:
            # Avoid echoing full response bodies, which may contain customer data.
            raise ShopifyError(f"Shopify returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ShopifyError("Shopify returned an invalid JSON response.") from exc
        if payload.get("errors"):
            messages = "; ".join(str(error.get("message", "GraphQL error")) for error in payload["errors"])
            raise ShopifyError(messages[:800])
        return payload.get("data") or {}

    def recent_orders(self, limit: int = 12) -> list[OrderSummary]:
        query = """
        query RecentOrders($first: Int!) {
          orders(first: $first, sortKey: CREATED_AT, reverse: true) {
            nodes {
              name createdAt displayFinancialStatus
              totalPriceSet { shopMoney { amount currencyCode } }
              customer { displayName }
            }
          }
        }
        """
        data = self.graphql(query, {"first": max(1, min(limit, 50))})
        result: list[OrderSummary] = []
        for order in data.get("orders", {}).get("nodes", []):
            money = order.get("totalPriceSet", {}).get("shopMoney", {})
            result.append(OrderSummary(
                name=order.get("name") or "Order",
                created_at=order.get("createdAt") or "",
                customer=(order.get("customer") or {}).get("displayName") or "Guest",
                total=money.get("amount") or "0.00",
                currency=money.get("currencyCode") or "",
                financial_status=order.get("displayFinancialStatus") or "UNKNOWN",
            ))
        return result

    def create_draft_product(
        self, *, title: str, price: float, description_html: str,
        seo_title: str, seo_description: str, tags: list[str], image_url: str = ""
    ) -> dict:
        try:
            decimal_price = Decimal(str(price)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as exc:
            raise ShopifyError("Price must be a valid positive amount.") from exc
        if not decimal_price.is_finite() or decimal_price <= 0 or decimal_price > Decimal("100000000"):
            raise ShopifyError("Price must be greater than zero and within Shopify's supported range.")
        title = title.strip()
        if not title or len(title) > 255:
            raise ShopifyError("Product title must contain 1–255 characters.")

        media = []
        if image_url.strip():
            parsed = urlparse(image_url.strip())
            if parsed.scheme != "https" or not parsed.netloc:
                raise ShopifyError("Image URL must be a public HTTPS URL.")
            media = [{
                "originalSource": image_url.strip(),
                "mediaContentType": "IMAGE",
                "alt": title[:255],
            }]

        create_mutation = """
        mutation CreateDraftProduct($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
          productCreate(product: $product, media: $media) {
            product {
              id title
              variants(first: 1) { nodes { id } }
            }
            userErrors { field message }
          }
        }
        """
        product = {
            "title": title,
            "descriptionHtml": description_html,
            "status": "DRAFT",
            "seo": {"title": seo_title[:70], "description": seo_description[:320]},
            "tags": tags[:20],
        }
        result = self.graphql(create_mutation, {"product": product, "media": media})
        created = result.get("productCreate") or {}
        errors = created.get("userErrors") or []
        if errors:
            raise ShopifyError("; ".join(item.get("message", "Product creation failed") for item in errors)[:800])
        shopify_product = created.get("product") or {}
        variants = (shopify_product.get("variants") or {}).get("nodes") or []
        if not variants:
            raise ShopifyError("Shopify created the product but returned no initial variant; price was not set.")

        price_mutation = """
        mutation SetInitialVariantPrice($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants { id price }
            userErrors { field message }
          }
        }
        """
        priced = self.graphql(price_mutation, {
            "productId": shopify_product["id"],
            "variants": [{"id": variants[0]["id"], "price": str(decimal_price)}],
        }).get("productVariantsBulkUpdate") or {}
        price_errors = priced.get("userErrors") or []
        if price_errors:
            raise ShopifyError(
                "Product draft was created, but Shopify could not set its price: "
                + "; ".join(item.get("message", "Price update failed") for item in price_errors)[:600]
            )
        return {"id": shopify_product.get("id", ""), "title": shopify_product.get("title", title), "price": str(decimal_price)}

