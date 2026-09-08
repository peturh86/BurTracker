"""Krónan product lookup and HA product-list client."""
import asyncio
from collections import OrderedDict
import time
import hashlib
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
    def __init__(self, session, token, increment_store=None):
        self.session = session
        self.token = token.strip()
        self.cache = OrderedDict()
        self.lock = asyncio.Lock()
        self.retry_after = 0.0
        self.list_lock = asyncio.Lock()
        self.list_token = None
        self.increment_store = increment_store
        self.increments = None

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


    @staticmethod
    def _quantity(result, sku):
        if not isinstance(result, dict) or not isinstance(result.get("items"), list):
            raise LookupFailure("list_failed")
        matches = []
        for item in result["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("product"), dict):
                raise LookupFailure("list_failed")
            if item["product"].get("sku") == sku:
                quantity = item.get("quantity")
                if type(quantity) is not int or not 0 <= quantity <= 10000:
                    raise LookupFailure("list_failed")
                matches.append(quantity)
        if len(matches) > 1:
            raise LookupFailure("list_failed")
        return matches[0] if matches else 0

    async def _save_increments(self):
        if self.increment_store is not None:
            await self.increment_store.async_save(self.increments)

    async def add_to_shopping_list(self, product, request_key):
        """Increment once per request. Never automatically replay an uncertain write."""
        if not request_key:
            raise LookupFailure("request_required")
        key = hashlib.sha256((self.token + "\0" + request_key).encode()).hexdigest()
        try:
            async with asyncio.timeout(12):
                async with self.list_lock:
                    if self.increments is None:
                        self.increments = (await self.increment_store.async_load()
                                           if self.increment_store is not None else None) or {}
                    previous = self.increments.get(key)
                    if previous:
                        if previous["sku"] != product.sku:
                            raise LookupFailure("request_conflict")
                        if previous["state"] != "confirmed":
                            raise LookupFailure("write_uncertain")
                        return previous["quantity"]
                    token = await self._ensure_list()
                    path = f"/product-lists/{quote(token, safe='')}/"
                    current = await self._list_request("GET", path)
                    quantity = self._quantity(current, product.sku) + 1
                    if quantity > 10000:
                        raise LookupFailure("quantity_limit")
                    # Write-ahead record protects against timeout/restart ambiguity.
                    self.increments[key] = {"sku": product.sku, "state": "uncertain",
                                            "quantity": quantity}
                    await self._save_increments()
                    result = await self._list_request(
                        "POST", path + "update-item/",
                        json={"sku": product.sku, "quantity": quantity},
                    )
                    try:
                        confirmed = self._quantity(result, product.sku)
                    except LookupFailure as err:
                        raise LookupFailure("write_uncertain") from err
                    if confirmed != quantity:
                        raise LookupFailure("write_uncertain")
                    # Keep memory uncertain too if confirmation cannot be persisted.
                    self.increments[key]["state"] = "confirmed"
                    try:
                        await self._save_increments()
                    except BaseException:
                        self.increments[key]["state"] = "uncertain"
                        raise
                    return quantity
        except LookupFailure as err:
            if err.status == "list_missing":
                self.list_token = None
            raise
        except (TimeoutError, OSError) as err:
            raise LookupFailure("write_uncertain") from err
