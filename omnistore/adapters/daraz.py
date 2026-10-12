"""Daraz Open Platform adapter contract; API signing is region-specific."""

from typing import Any

from .base import IntegrationScaffoldError, PlatformAdapter
from ..models import UniversalProduct


class DarazAdapter(PlatformAdapter):
    platform = "daraz"
    is_scaffold = True

    def _pending(self) -> None:
        raise IntegrationScaffoldError(
            "Daraz adapter is a scaffold: implement the seller-region API signature, "
            "timestamp/nonce rules, and category-specific product schema before live use."
        )

    def create_product(self, product: UniversalProduct) -> dict[str, Any]:
        self._pending()

    def fetch_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._pending()

    def update_inventory(self, product_id: str, quantity: int, **kwargs: Any) -> dict[str, Any]:
        self._pending()
