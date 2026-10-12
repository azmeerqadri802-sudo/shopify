"""Platform-neutral commerce models shared by the agent and adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(slots=True)
class UniversalProduct:
    """Canonical product form; each channel adapter maps it to its own API."""

    title: str
    description: str
    price: Decimal
    currency: str = "USD"
    sku: str = ""
    vendor: str = ""
    product_type: str = "Digital accessory"
    tags: list[str] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    inventory_quantity: int = 0
    platform_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        self.description = self.description.strip()
        try:
            self.price = Decimal(str(self.price))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("Product price must be a valid number") from exc
        if not self.title:
            raise ValueError("Product title is required")
        if self.price < 0:
            raise ValueError("Product price cannot be negative")
        if self.inventory_quantity < 0:
            raise ValueError("Inventory quantity cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["price"] = str(self.price)
        return result

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "UniversalProduct":
        title = str(row.get("title") or row.get("name") or row.get("product_name") or "").strip()
        raw_tags = row.get("tags", [])
        if isinstance(raw_tags, str):
            tags = [part.strip() for part in raw_tags.replace(";", ",").split(",") if part.strip()]
        elif isinstance(raw_tags, list):
            tags = [str(part).strip() for part in raw_tags if str(part).strip()]
        else:
            tags = []
        images = row.get("image_urls") or row.get("image_url") or row.get("images") or []
        if isinstance(images, str):
            images = [part.strip() for part in images.split(",") if part.strip()]
        if not isinstance(images, list):
            images = []
        try:
            quantity = int(float(row.get("inventory_quantity") or row.get("quantity") or 0))
        except (ValueError, TypeError):
            quantity = 0
        return cls(
            title=title,
            description=str(row.get("description") or "").strip(),
            price=Decimal(str(row.get("price") or 0)),
            currency=str(row.get("currency") or "USD").upper(),
            sku=str(row.get("sku") or "").strip(),
            vendor=str(row.get("vendor") or "").strip(),
            product_type=str(row.get("product_type") or "Digital accessory").strip(),
            tags=tags,
            image_urls=[str(url).strip() for url in images if str(url).strip()],
            inventory_quantity=quantity,
        )
