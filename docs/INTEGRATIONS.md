# Marketplace integration status

The adapter contract in `omnistore/adapters/base.py` standardizes `create_product`, `fetch_orders`, and `update_inventory` around `UniversalProduct`.

| Channel | V3 implementation | Notes |
| --- | --- | --- |
| Shopify | Admin REST API adapter | Creates draft products, reads orders, and sets inventory when item/location IDs are supplied. A public HTTPS relay is needed for remote webhooks. |
| WooCommerce | REST API adapter | Creates draft products, reads orders, and updates stock; HTTPS is required. |
| Amazon | SP-API adapter | LWA refresh, optional STS role assumption, AWS SigV4, listings and order polling. Product type and marketplace attributes must match Amazon's current schema. |
| eBay | Sell Inventory/Fulfillment API adapter | Uses a user access token and configured listing policies, category, and merchant location. |
| TikTok Shop | Scaffold only | Region-specific Open API signing, OAuth refresh, and category mapping remain to be implemented before live use. |
| Daraz | Scaffold only | Seller-region signing, timestamp rules, and category-specific schemas remain to be implemented before live use. |

The Daraz and TikTok Shop classes expose all three adapter methods but deliberately raise `IntegrationScaffoldError`. They are not represented as connected channels and cannot silently accept a listing. Do not treat saved credentials as proof an integration is live.

## Order intake

The desktop app listens on `127.0.0.1:8787` by default and verifies Shopify/WooCommerce HMAC signatures against each platform's saved webhook secret. Since Shopify and WooCommerce cannot call a loopback address, route the webhook through a trusted public HTTPS integration that preserves the raw body and signature. Do not expose the receiver publicly without TLS, rate limiting, and a hardened reverse proxy. Amazon polling requires SP-API credentials; Daraz polling logs the scaffold status until its API is implemented.

Incoming order payloads are encrypted at rest and deduplicated by platform/order ID. WhatsApp reports contain only order identifiers, amounts, status and item names. AI formatting falls back to a local template if Gemini is unavailable. Meta WhatsApp Cloud API requires an opted-in recipient and may require an approved template for business-initiated messages.

## Product imports

Excel, CSV, DOCX tables, and Google Sheets are read sequentially, with a 1,000 row limit per run. The first row/table row must contain a `title` (or `name` / `product_name`) and `price` column. Optional columns include `description`, `sku`, `tags`, `image_url`, `image_urls`, `quantity`, `vendor`, `product_type`, and `currency`. Google Sheets access needs a Google API key for public sheets or a service-account JSON key for private sheets; share the target spreadsheet with that service account.

AI normalizes product copy once per row into the universal product model. That same model is passed to each selected adapter. Bulk listing failures are recorded per row and platform; successful calls are not rolled back when another marketplace fails.
