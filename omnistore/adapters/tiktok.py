"""TikTok Shop adapter contract; OAuth and request signing vary by market."""

from typing import Any

from .base import IntegrationScaffoldError, PlatformAdapter
from ..models import UniversalProduct


class TikTokShopAdapter(PlatformAdapter):
    platform = "tiktok_shop"
    is_scaffold = True

    def _pending(self) -> None:
        raise IntegrationScaffoldError(
            "TikTok Shop adapter is a scaffold: implement the region-specific Open API signing, "
            "authorization refresh, and product schema before enabling live writes."
        )

    def create_product(self, product: UniversalProduct) -> dict[str, Any]:
        self._pending()

    def fetch_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._pending()

    def update_inventory(self, product_id: str, quantity: int, **kwargs: Any) -> dict[str, Any]:
        self._pending()
