"""Marketplace API adapters."""

from .amazon import AmazonSPAPIAdapter
from .daraz import DarazAdapter
from .ebay import EbayAdapter
from .tiktok import TikTokShopAdapter
from .shopify import ShopifyAdapter
from .woocommerce import WooCommerceAdapter

ADAPTERS = {
    "shopify": ShopifyAdapter,
    "amazon": AmazonSPAPIAdapter,
    "ebay": EbayAdapter,
    "woocommerce": WooCommerceAdapter,
    "tiktok_shop": TikTokShopAdapter,
    "daraz": DarazAdapter,
}
