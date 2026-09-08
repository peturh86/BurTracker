"""Krónan product lookup and HA product-list client."""
import asyncio
from collections import OrderedDict
import time
from urllib.parse import quote

import aiohttp

from .retailer import LookupFailure, Product

BASE_URL = "https://api.kronan.is/api/v1"


def parse_product(payload):
    """The dedicated barcode endpoint returns PublicProductDetail directly."""
    if not isinstance(payload, dict):
        raise LookupFailure()
    sku, name = payload.get("sku"), payload.get("name")
    if not isinstance(sku, str) or not sku.strip():
        raise LookupFailure()
    if (not isinstance(name, str) or not name.strip() or len(name) > 128
            or any(ord(c) < 32 for c in name)):
        raise LookupFailure()
    price = payload.get("discountedPrice") if payload.get("onSale") is True else payload.get("price")
    if type(price) is not int or price < 0:
        price = None
    return Product("kronan", sku, name.strip(), price)


class KronanRetailer:
    def __init__(self, session, token):
        self.session = session
        self.token = token.strip()
        self.cache = OrderedDict()
        self.lock = asyncio.Lock()
        self.retry_after = 0.0
        self.list_lock = asyncio.Lock()
        self.list_token = None

    async def lookup(self, barcode):
        if not self.token:
            raise LookupFailure("auth_required")
        try:
            # Includes lock wait, so a burst cannot queue indefinitely.
            async with asyncio.timeout(10):
                async with self.lock:
                    now = time.monotonic()
                    cached = self.cache.get(barcode)
                    if cached and cached[0] > now:
                        self.cache.move_to_end(barcode)
                        return cached[1]
                    if now < self.retry_after:
                        raise LookupFailure("rate_limited")
                    url = f"{BASE_URL}/products/barcode/{quote(barcode, safe='')}/"
                    async with self.session.get(
                        url, headers={"Authorization": f"AccessToken {self.token}"},
                        allow_redirects=False,
                    ) as response:
                        if response.status in (401, 403):
                            raise LookupFailure("auth_required")
                        if response.status == 429:
                            try:
                                seconds = float(response.headers.get("Retry-After", "200"))
                            except ValueError:
                                seconds = 200
                            self.retry_after = now + max(1, min(seconds, 3600))
                            raise LookupFailure("rate_limited")
                        if response.status == 404:
                            product = None
                        elif response.status == 200:
                            product = parse_product(await response.json())
                        else:
                            raise LookupFailure()
                    self.cache[barcode] = (time.monotonic() + (300 if product else 60), product)
                    self.cache.move_to_end(barcode)
                    while len(self.cache) > 256:
                        self.cache.popitem(last=False)
                    return product
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise LookupFailure() from err

    async def _list_request(self, method, path, **kwargs):
        if not self.token:
            raise LookupFailure("auth_required")
        if time.monotonic() < self.retry_after:
            raise LookupFailure("rate_limited")
        try:
            async with self.session.request(
                method, BASE_URL + path,
                headers={"Authorization": f"AccessToken {self.token}"},
                allow_redirects=False, **kwargs,
            ) as response:
                if response.status in (401, 403):
                    raise LookupFailure("auth_required")
                if response.status == 429:
                    self.retry_after = time.monotonic() + 200
                    raise LookupFailure("rate_limited")
                if response.status == 404:
                    raise LookupFailure("list_missing")
                if response.status not in (200, 201):
                    raise LookupFailure("write_uncertain" if method == "POST" and response.status >= 500 else "list_failed")
                return await response.json()
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise LookupFailure("write_uncertain" if method == "POST" else "list_failed") from err

    async def _ensure_list(self):
        if self.list_token:
            return self.list_token
        matches = []
        offset = 0
        for _ in range(100):
            page = await self._list_request(
                "GET", "/product-lists/", params={"limit": 100, "offset": offset}
            )
            if not isinstance(page, dict) or not isinstance(page.get("results"), list):
                raise LookupFailure("list_failed")
            rows = page["results"]
            count = page.get("count")
            if type(count) is not int or count < 0:
                raise LookupFailure("list_failed")
            for row in rows:
                if not isinstance(row, dict):
                    raise LookupFailure("list_failed")
                if row.get("name") == "HA":
                    matches.append(row)
            offset += len(rows)
            if offset >= count:
                break
            if not rows:
                raise LookupFailure("list_failed")
        else:
            raise LookupFailure("list_failed")
        if len(matches) > 1:
            raise LookupFailure("list_ambiguous")
        result = matches[0] if matches else await self._list_request(
            "POST", "/product-lists/",
            json={"name": "HA", "description": "Household shopping from BurTracker"},
        )
        if not isinstance(result, dict) or result.get("name") != "HA":
            raise LookupFailure("list_failed")
        token = result.get("token")
        if not isinstance(token, str) or not token:
            raise LookupFailure("list_failed")
        self.list_token = token
        return token

    async def ensure_shopping_list(self):
        """Find or create HA at startup; never create after an incomplete search."""
        try:
            async with asyncio.timeout(12):
                async with self.list_lock:
                    return await self._ensure_list()
        except TimeoutError as err:
            # A create may have reached the server. Next attempt searches first.
            raise LookupFailure("write_uncertain") from err

    async def add_to_shopping_list(self, product):
        """Ensure SKU is present without changing the quantity of existing items."""
        try:
            async with asyncio.timeout(12):
                async with self.list_lock:
                    token = await self._ensure_list()
                    result = await self._list_request(
                        "POST", f"/product-lists/{quote(token, safe='')}/batch-add-items/",
                        json={"skus": [product.sku]},
                    )
                    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
                        raise LookupFailure("write_uncertain")
                    if not any(
                        isinstance(item, dict) and isinstance(item.get("product"), dict)
                        and item["product"].get("sku") == product.sku
                        and type(item.get("quantity")) is int and item["quantity"] > 0
                        for item in result["items"]
                    ):
                        raise LookupFailure("write_uncertain")
                    return "kronan_added"
        except LookupFailure as err:
            if err.status == "list_missing":
                self.list_token = None
            raise
        except TimeoutError as err:
            raise LookupFailure("write_uncertain") from err
