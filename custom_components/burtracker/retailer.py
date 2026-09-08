"""Retailer-neutral product lookup contract."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Product:
    provider: str
    sku: str
    name: str
    price_isk: int | None = None


class LookupFailure(Exception):
    """A failed lookup, distinct from a confirmed absent product."""

    def __init__(self, status="lookup_failed"):
        super().__init__(status)
        self.status = status


class Retailer(Protocol):
    async def lookup(self, barcode: str) -> Product | None:
        """Return an exact barcode match, or None for not found."""


    async def ensure_shopping_list(self) -> str:
        """Initialize the household's retailer-owned product list."""

    async def add_to_shopping_list(self, product: Product, request_key: str) -> int:
        """Increment a product once per request and return confirmed quantity."""
