"""Read-only client for the documented Krónan public API."""
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
    return Product("kronan", sku, name.strip())


class KronanRetailer:
    def __init__(self, session, token):
        self.session = session
        self.token = token.strip()
        self.cache = OrderedDict()
        self.lock = asyncio.Lock()
        self.retry_after = 0.0

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
                    self.cache[barcode] = (time.monotonic() + (3600 if product else 60), product)
                    self.cache.move_to_end(barcode)
                    while len(self.cache) > 256:
                        self.cache.popitem(last=False)
                    return product
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise LookupFailure() from err
