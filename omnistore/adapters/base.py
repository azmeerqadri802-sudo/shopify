"""Shared adapter contracts and safe HTTP helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import requests

from ..models import UniversalProduct


class AdapterError(RuntimeError):
    """An actionable marketplace API or authorization error."""


class IntegrationScaffoldError(AdapterError):
    """Raised where a marketplace's signing/OAuth setup is not implemented."""


class PlatformAdapter(ABC):
    platform = "unknown"

    def __init__(self, credentials: dict[str, Any]) -> None:
        self.credentials = credentials
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "OmniStoreAIManager/3.0"})

    @abstractmethod
    def create_product(self, product: UniversalProduct) -> dict[str, Any]:
        """Create or list a canonical product on this channel."""

    @abstractmethod
    def fetch_orders(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch recent orders in platform-native format."""

    @abstractmethod
    def update_inventory(self, product_id: str, quantity: int, **kwargs: Any) -> dict[str, Any]:
        """Set available inventory for a platform listing."""

    @staticmethod
    def check(response: requests.Response) -> dict[str, Any]:
        if not response.ok:
            excerpt = response.text[:600].replace("\n", " ")
            raise AdapterError(f"Marketplace API returned HTTP {response.status_code}: {excerpt}")
        if not response.content:
            return {}
        try:
            result = response.json()
        except ValueError as exc:
            raise AdapterError("Marketplace API returned malformed JSON") from exc
        return result if isinstance(result, dict) else {"data": result}
