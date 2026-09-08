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

    def test_catalog_price_and_discount(self):
        base = {"sku": "1", "name": "Milk", "price": 499}
        self.assertEqual(parse_product(base).price_isk, 499)
        self.assertEqual(parse_product(base | {"onSale": True, "discountedPrice": 399}).price_isk, 399)
        self.assertIsNone(parse_product(base | {"price": None}).price_isk)
        self.assertIsNone(parse_product(base | {"price": True}).price_isk)
        self.assertIsNone(parse_product(base | {"price": -1}).price_isk)

    def test_unicode_product_name(self):
        self.assertEqual(parse_product({"sku": "1", "name": "Mj\u00f3lk"}).name,
                         "Mj\u00f3lk")

class ListSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


class ProductListTests(unittest.IsolatedAsyncioTestCase):
    def client(self, *responses):
        session = ListSession(responses)
        return KronanRetailer(session, "test-token"), session

    async def test_finds_existing_list_on_later_page(self):
        client, session = self.client(
            Response(payload={"count": 2, "results": [{"name": "Other", "token": "other"}]}),
            Response(payload={"count": 2, "results": [{"name": "HA", "token": "ha-token"}]}),
        )
        self.assertEqual(await client.ensure_shopping_list(), "ha-token")
        self.assertEqual(await client.ensure_shopping_list(), "ha-token")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[1][2]["params"]["offset"], 1)

    async def test_creates_once_for_concurrent_initialization(self):
        client, session = self.client(
            Response(payload={"count": 0, "results": []}),
            Response(status=201, payload={"name": "HA", "token": "new-token"}),
        )
        self.assertEqual(await asyncio.gather(
            client.ensure_shopping_list(), client.ensure_shopping_list()),
            ["new-token", "new-token"])
        self.assertEqual([c[0] for c in session.calls], ["GET", "POST"])
        self.assertEqual(session.calls[1][2]["json"]["name"], "HA")

    async def test_incomplete_discovery_never_creates(self):
        for payload in ({}, {"count": 2, "results": []}):
            client, session = self.client(Response(payload=payload))
            with self.assertRaises(LookupFailure):
                await client.ensure_shopping_list()
            self.assertEqual(len(session.calls), 1)

    async def test_duplicate_names_do_not_pick_arbitrarily(self):
        client, session = self.client(Response(payload={
            "count": 2, "results": [{"name": "HA", "token": "a"}, {"name": "HA", "token": "b"}]}))
        with self.assertRaises(LookupFailure) as ctx:
            await client.ensure_shopping_list()
        self.assertEqual(ctx.exception.status, "list_ambiguous")
        self.assertEqual(len(session.calls), 1)

    async def test_batch_add_uses_sku_and_requires_confirmation(self):
        client, session = self.client(Response(payload={
            "items": [{"product": {"sku": "123"}, "quantity": 2}]}))
        client.list_token = "ha-token"
        product = parse_product({"sku": "123", "name": "Milk"})
        self.assertEqual(await client.add_to_shopping_list(product), "kronan_added")
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/product-lists/ha-token/batch-add-items/"))
        self.assertEqual(kwargs["json"], {"skus": ["123"]})

    async def test_unconfirmed_add_is_not_success(self):
        client, _ = self.client(Response(payload={"items": []}))
        client.list_token = "ha-token"
        with self.assertRaises(LookupFailure) as ctx:
            await client.add_to_shopping_list(parse_product({"sku": "123", "name": "Milk"}))
        self.assertEqual(ctx.exception.status, "write_uncertain")

    async def test_deleted_list_invalidates_cached_token(self):
        client, _ = self.client(Response(status=404))
        client.list_token = "ha-token"
        with self.assertRaises(LookupFailure):
            await client.add_to_shopping_list(parse_product({"sku": "123", "name": "Milk"}))
        self.assertIsNone(client.list_token)

    async def test_auth_failure_does_not_create(self):
        client, session = self.client(Response(status=401))
        with self.assertRaises(LookupFailure) as ctx:
            await client.ensure_shopping_list()
        self.assertEqual(ctx.exception.status, "auth_required")
        self.assertEqual(len(session.calls), 1)


if __name__ == "__main__":
    unittest.main()
