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


    async def test_quantity_increments_and_replayed_request_does_not(self):
        client, session = self.client(
            Response(payload={"items": [{"product": {"sku": "123"}, "quantity": 2}]}),
            Response(payload={"items": [{"product": {"sku": "123"}, "quantity": 3}]}),
            Response(payload={"items": [{"product": {"sku": "123"}, "quantity": 3}]}),
            Response(payload={"items": [{"product": {"sku": "123"}, "quantity": 4}]}),
        )
        client.list_token = "ha-token"
        product = parse_product({"sku": "123", "name": "Milk"})
        result = await asyncio.gather(
            client.add_to_shopping_list(product, "kitchen:r1"),
            client.add_to_shopping_list(product, "bin:r2"),
        )
        self.assertEqual(result, [3, 4])
        self.assertEqual(await client.add_to_shopping_list(product, "kitchen:r1"), 3)
        self.assertEqual(len(session.calls), 4)
        self.assertTrue(session.calls[1][1].endswith("/update-item/"))
        self.assertEqual(session.calls[1][2]["json"], {"sku": "123", "quantity": 3})
        self.assertEqual(session.calls[3][2]["json"]["quantity"], 4)

    async def test_unconfirmed_increment_is_not_retried(self):
        client, session = self.client(
            Response(payload={"items": []}),
            Response(payload={"items": []}),
        )
        client.list_token = "ha-token"
        product = parse_product({"sku": "123", "name": "Milk"})
        for _ in range(2):
            with self.assertRaises(LookupFailure) as ctx:
                await client.add_to_shopping_list(product, "r1")
            self.assertEqual(ctx.exception.status, "write_uncertain")
        self.assertEqual(len(session.calls), 2)

    async def test_deleted_list_invalidates_cached_token(self):
        client, _ = self.client(Response(status=404))
        client.list_token = "ha-token"
        with self.assertRaises(LookupFailure):
            await client.add_to_shopping_list(parse_product({"sku": "123", "name": "Milk"}), "r1")
        self.assertIsNone(client.list_token)

    async def test_missing_request_id_never_writes(self):
        client, session = self.client()
        with self.assertRaises(LookupFailure):
            await client.add_to_shopping_list(parse_product({"sku": "123", "name": "Milk"}), "")
        self.assertEqual(session.calls, [])

    async def test_quantity_limit_does_not_write(self):
        client, session = self.client(Response(payload={
            "items": [{"product": {"sku": "123"}, "quantity": 10000}]}))
        client.list_token = "ha-token"
        with self.assertRaises(LookupFailure) as ctx:
            await client.add_to_shopping_list(parse_product({"sku": "123", "name": "Milk"}), "r1")
        self.assertEqual(ctx.exception.status, "quantity_limit")
        self.assertEqual(len(session.calls), 1)

    async def test_restart_retains_confirmed_and_uncertain_request_ids(self):
        from copy import deepcopy
        class MemoryStore:
            data = None
            async def async_load(self):
                return deepcopy(self.data)
            async def async_save(self, data):
                self.data = deepcopy(data)
        store = MemoryStore()
        client, session = self.client(
            Response(payload={"items": []}),
            Response(payload={"items": [{"product": {"sku": "123"}, "quantity": 1}]}),
            Response(payload={"items": [{"product": {"sku": "123"}, "quantity": 1}]}),
            Response(status=500),
        )
        client.increment_store = store
        client.list_token = "ha-token"
        product = parse_product({"sku": "123", "name": "Milk"})
        self.assertEqual(await client.add_to_shopping_list(product, "r1"), 1)
        with self.assertRaises(LookupFailure):
            await client.add_to_shopping_list(product, "r2")
        restarted, unused = self.client()
        restarted.increment_store = store
        self.assertEqual(await restarted.add_to_shopping_list(product, "r1"), 1)
        with self.assertRaises(LookupFailure) as ctx:
            await restarted.add_to_shopping_list(product, "r2")
        self.assertEqual(ctx.exception.status, "write_uncertain")
        self.assertEqual(unused.calls, [])

    async def test_auth_failure_does_not_create(self):
        client, session = self.client(Response(status=401))
        with self.assertRaises(LookupFailure) as ctx:
            await client.ensure_shopping_list()
        self.assertEqual(ctx.exception.status, "auth_required")
        self.assertEqual(len(session.calls), 1)

    async def test_search_products_returns_catalog_price_and_provenance(self):
        hit = {"sku": "cod-1", "name": "Þorskur 500 g", "price": 2499,
               "priceInfo": "500 g", "chargedByWeight": False,
               "pricePerKilo": 4998, "temporaryShortage": False,
               "detail": {"onSale": True, "discountedPrice": 1999,
                          "qtyInSalesUnit": 500}}
        client, session = self.client(Response(payload={
            "count": 1, "page": 1, "pageCount": 1, "hasNextPage": False,
            "hits": [hit],
        }))
        result = await client.search_products("þorskur")
        self.assertEqual(result["source"], "Krónan Public API")
        self.assertEqual(result["items"][0]["price_isk"], 1999)
        self.assertEqual(result["items"][0]["regular_price_isk"], 2499)
        self.assertEqual(result["items"][0]["sales_unit_quantity"], 500)
        self.assertEqual(result["items"][0]["availability_scope"], "home_delivery_selection")
        method, url, options = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/products/search/"))
        self.assertEqual(options["json"], {"query": "þorskur", "page": 1,
                                           "pageSize": 15, "withDetail": True})
        self.assertEqual(options["headers"]["Authorization"], "AccessToken test-token")

    async def test_store_search_is_scoped_and_not_a_stock_claim(self):
        client, session = self.client(Response(payload={"hits": [], "count": 0,
                                                        "page": 1, "pageCount": 0,
                                                        "hasNextPage": False}))
        result = await client.search_products("kartöflur", store="REYK")
        self.assertEqual(result["availability_scope"], "specific_store")
        self.assertEqual(result["store"], "REYK")
        self.assertIn("not a guaranteed shelf-stock check", result["availability_note"])
        method, url, options = session.calls[0]
        self.assertTrue(url.endswith("/shopping-notes/search/"))
        self.assertEqual(options["json"]["store"], "REYK")

    async def test_scan_n_go_stores_returns_ids_and_names(self):
        client, session = self.client(Response(payload=[
            {"extId": "REYK", "name": "Krónan Reykjavík"},
        ]))
        stores = await client.scan_n_go_stores()
        self.assertEqual(stores, [{"ext_id": "REYK", "name": "Krónan Reykjavík",
                                  "source": "Krónan Public API"}])
        self.assertEqual(session.calls[0][0], "GET")
        self.assertTrue(session.calls[0][1].endswith("/shopping-notes/scan-n-go-stores/"))

    async def test_search_recipes_strips_access_tokens(self):
        client, session = self.client(Response(payload={
            "count": 1, "page": 1, "recipes": [{"name": "Soup", "slug": "soup",
              "token": "must-not-leak", "servings": 4}],
            "availableTags": {},
        }))
        result = await client.search_recipes("soup")
        self.assertEqual(result["recipes"], [{"name": "Soup", "slug": "soup", "servings": 4}])
        self.assertNotIn("must-not-leak", repr(result))
        self.assertEqual(session.calls[0][2]["json"], {"query": "soup", "page": 1})

    async def test_recipe_quote_refreshes_linked_prices_and_scales_packages(self):
        recipe = {"slug": "soup", "name": "Soup", "displayName": "Cod soup",
                  "servings": 4, "ingredients": "cod and cream", "directions": "Cook",
                  "items": [{"quantity": 1, "product": {"sku": "fish"}}],
                  "essentials": [{"quantity": 2, "product": {"sku": "cream"}}]}
        fish = {"sku": "fish", "name": "Cod pack", "price": 1100, "discountedPrice": 1100,
                "onSale": False, "priceInfo": "500 g", "chargedByWeight": False,
                "temporaryShortage": False, "tags": []}
        cream = fish | {"sku": "cream", "name": "Cream", "price": 400}
        client, session = self.client(Response(payload=recipe), Response(payload=fish), Response(payload=cream))
        quote = await client.quote_recipe("soup", 5)
        self.assertTrue(quote["verified_product_quote"])
        self.assertFalse(quote["complete"])
        self.assertFalse(quote["saveable"])
        self.assertEqual([line["packages"] for line in quote["product_lines"]], [2, 3])
        self.assertEqual(quote["total_package_cost_isk"], 3400)
        self.assertEqual(quote["cost_per_portion_isk"], 680)
        self.assertEqual(len(session.calls), 3)

    async def test_generated_quote_uses_live_kr_n_price(self):
        product = {"sku": "123", "name": "Olive oil", "price": 500,
                   "discountedPrice": 500, "onSale": False, "temporaryShortage": False,
                   "priceInfo": "500 ml", "chargedByWeight": False, "tags": [],
                   "nutrition": {}}
        client, session = self.client(Response(payload=product))
        quote = await client.quote_generated_meal("Roast veg", 3.5, [{
            "ingredient": "olive oil", "sku": "123", "packages": 1,
            "quantity_basis": "one 500 ml bottle covers the recipe",
        }], "Roast vegetables")
        self.assertEqual(quote["total_package_cost_isk"], 500)
        self.assertEqual(quote["product_lines"][0]["product"]["sku"], "123")
        self.assertEqual(session.calls[0][1].endswith("/products/123/"), True)

    async def test_lactose_free_preference_blocks_unverified_dairy_product(self):
        product = {"sku": "cream", "name": "Sýrður rjómi", "price": 400,
                   "discountedPrice": 400, "onSale": False, "temporaryShortage": False,
                   "priceInfo": "180 g", "chargedByWeight": False,
                   "categoryPath": "Mjólkurvörur / Sýrður rjómi", "tags": [], "nutrition": {}}
        client, _ = self.client(Response(payload=product))
        quote = await client.quote_generated_meal("Dinner", 4, [{
            "ingredient": "sýrður rjómi", "sku": "cream", "packages": 1,
        }], dietary_preferences={"lactose_free": True})
        self.assertFalse(quote["complete"])
        self.assertEqual(quote["blocked_skus"], ["cream"])
        self.assertEqual(quote["dietary_conflicts"][0]["sku"], "cream")
        self.assertIsNone(quote["total_package_cost_isk"])

    async def test_kr_n_lactose_free_tag_allows_dairy_product(self):
        product = {"sku": "cream-lf", "name": "Sýrður rjómi laktósafrír", "price": 500,
                   "discountedPrice": 500, "onSale": False, "temporaryShortage": False,
                   "priceInfo": "180 g", "chargedByWeight": False,
                   "categoryPath": "Mjólkurvörur / Sýrður rjómi", "tags": [{"slug": "lactosefree"}],
                   "nutrition": {}}
        client, _ = self.client(Response(payload=product))
        quote = await client.quote_generated_meal("Dinner", 4, [{
            "ingredient": "lactose-free sour cream", "sku": "cream-lf", "packages": 1,
        }], dietary_preferences={"lactose_free": True})
        self.assertTrue(quote["complete"])
        self.assertEqual(quote["total_package_cost_isk"], 500)

    async def test_product_detail_rejects_sku_mismatch(self):
        client, _ = self.client(Response(payload={"sku": "other", "name": "Not the requested SKU"}))
        with self.assertRaises(LookupFailure):
            await client.product_detail("wanted")

    async def test_search_validates_without_network(self):
        client, session = self.client()
        for query, page in (("", 1), ("x" * 65, 1), ("milk", 0)):
            with self.assertRaises(ValueError):
                await client.search_products(query, page=page)
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
