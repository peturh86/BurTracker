"""Provider tests with simulated HTTP; no real credentials."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

base = Path(__file__).resolve().parents[1] / "custom_components/burtracker"
package = types.ModuleType("burtracker_test")
package.__path__ = [str(base)]
sys.modules["burtracker_test"] = package
from burtracker_test.kronan import KronanRetailer, parse_product
from burtracker_test.retailer import LookupFailure


class Response:
    def __init__(self, status=200, payload=None, headers=None, delay=0):
        self.status = status
        self.payload = payload
        self.headers = headers or {}
        self.delay = delay

    async def __aenter__(self):
        if self.delay:
            raise TimeoutError()
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.payload


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def make(self, status=200, payload=None, token="test-token", **kwargs):
        session = Session(Response(status, payload, **kwargs))
        return KronanRetailer(session, token), session

    async def test_exact_lookup_and_cached_repeats(self):
        client, session = self.make(payload={"sku": "123", "name": "Milk"})
        first, second = await asyncio.gather(client.lookup("00123"), client.lookup("00123"))
        self.assertEqual(first, second)
        self.assertEqual(first.name, "Milk")
        self.assertEqual(len(session.calls), 1)
        url, options = session.calls[0]
        self.assertTrue(url.endswith("/products/barcode/00123/"))
        self.assertEqual(options["headers"]["Authorization"], "AccessToken test-token")
        self.assertFalse(options["allow_redirects"])

    async def test_url_encodes_arbitrary_barcode(self):
        client, session = self.make(status=404)
        await client.lookup("ab/c?")
        self.assertTrue(session.calls[0][0].endswith("/ab%2Fc%3F/"))

    async def test_404_is_not_found_and_cached(self):
        client, session = self.make(status=404)
        self.assertIsNone(await client.lookup("123"))
        self.assertIsNone(await client.lookup("123"))
        self.assertEqual(len(session.calls), 1)

    async def test_no_token_does_not_make_request(self):
        client, session = self.make(token="")
        with self.assertRaises(LookupFailure) as ctx:
            await client.lookup("123")
        self.assertEqual(ctx.exception.status, "auth_required")
        self.assertFalse(session.calls)

    async def test_auth_errors_are_not_unknown_products(self):
        for status in (401, 403):
            client, _ = self.make(status=status)
            with self.assertRaises(LookupFailure) as ctx:
                await client.lookup("123")
            self.assertEqual(ctx.exception.status, "auth_required")

    async def test_429_applies_backoff(self):
        client, session = self.make(status=429, headers={"Retry-After": "30"})
        for code in ("123", "456"):
            with self.assertRaises(LookupFailure) as ctx:
                await client.lookup(code)
            self.assertEqual(ctx.exception.status, "rate_limited")
        self.assertEqual(len(session.calls), 1)

    async def test_server_error_and_timeout(self):
        for kwargs in ({"status": 500}, {"delay": 1}):
            client, _ = self.make(**kwargs)
            with self.assertRaises(LookupFailure) as ctx:
                await client.lookup("123")
            self.assertEqual(ctx.exception.status, "lookup_failed")

    async def test_invalid_success_payload(self):
        for payload in (None, [], {}, {"sku": "1", "name": ""},
                        {"sku": 1, "name": "Milk"}):
            client, _ = self.make(payload=payload)
            with self.assertRaises(LookupFailure):
                await client.lookup("123")

    def test_unicode_product_name(self):
        self.assertEqual(parse_product({"sku": "1", "name": "Mj\u00f3lk"}).name,
                         "Mj\u00f3lk")


if __name__ == "__main__":
    unittest.main()
