"""Krónan product lookup and HA product-list client."""
import asyncio
from collections import OrderedDict
import time
import hashlib
import math
from datetime import datetime, timezone
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


def lactose_conflict(product, preferences):
    """Conservatively flag obvious dairy products lacking Krónan's lactose-free tag."""
    if not isinstance(preferences, dict) or preferences.get("lactose_free") is not True:
        return None
    tags = product.get("tags") if isinstance(product.get("tags"), list) else []
    if any(isinstance(tag, dict) and tag.get("slug") == "lactosefree" for tag in tags):
        return None
    category = str(product.get("category_path") or "").casefold()
    category_segments = {segment.strip() for segment in category.split("/")}
    name = str(product.get("name") or "").casefold()
    markers = ("mjólk", "rjómi", "ostur", "smjör", "jógúrt", "skyr", "cream", "cheese", "butter", "yogurt")
    if "mjólkurvörur" in category_segments or any(word in name for word in markers):
        return {"sku": product.get("sku"), "product": product.get("name"),
                "reason": "Dairy-category product lacks Krónan's lactose-free tag; do not use for this household without confirmation."}
    return None


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

    async def search_products(self, query, store=None, page=1, page_size=15):
        """Search Krónan's published catalog; prices are observations, not checkout quotes."""
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 64:
            raise ValueError("query must contain 1 to 64 characters")
        if type(page) is not int or not 1 <= page <= 1000:
            raise ValueError("page must be an integer from 1 to 1000")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise ValueError("page_size must be an integer from 1 to 50")
        if store is not None and (not isinstance(store, str) or not store.strip() or len(store) > 20):
            raise ValueError("store must be a valid Krónan Scan & Go store ext_id")
        in_store = store is not None
        path = "/shopping-notes/search/" if in_store else "/products/search/"
        body = {"query": query.strip(), "page": page, "pageSize": page_size}
        if in_store:
            body["store"] = store.strip()
        else:
            body["withDetail"] = True
        try:
            async with asyncio.timeout(12):
                payload = await self._list_request("POST", path, json=body)
        except TimeoutError as err:
            raise LookupFailure("lookup_failed") from err
        if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
            raise LookupFailure("search_failed")
        observed_at = datetime.now(timezone.utc).isoformat()
        hits = []
        for item in payload["hits"]:
            if not isinstance(item, dict):
                raise LookupFailure("search_failed")
            sku, name = item.get("sku"), item.get("name")
            if not isinstance(sku, str) or not sku.strip() or not isinstance(name, str) or not name.strip():
                raise LookupFailure("search_failed")
            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            on_sale = detail.get("onSale") is True
            price = detail.get("discountedPrice") if on_sale else item.get("price")
            if type(price) is not int or price < 0:
                price = None
            regular = item.get("price")
            hits.append({
                "provider": "kronan", "sku": sku, "name": name.strip(),
                "price_isk": price,
                "regular_price_isk": regular if type(regular) is int and regular >= 0 else None,
                "on_sale": on_sale, "price_info": item.get("priceInfo"),
                "charged_by_weight": item.get("chargedByWeight") is True,
                "price_per_kilo_isk": item.get("pricePerKilo") if type(item.get("pricePerKilo")) is int else None,
                "sales_unit_quantity": detail.get("qtyInSalesUnit"),
                "temporary_shortage": item.get("temporaryShortage") is True,
                "availability_scope": "specific_store" if in_store else "home_delivery_selection",
                "availability_note": (
                    "Krónan Scan & Go store catalog result; not a guaranteed shelf-stock check."
                    if in_store else
                    "Krónan home-delivery product selection; not store-specific availability."
                ),
                "store": store.strip() if in_store else None,
                "observed_at": observed_at,
            })
        return {
            "source": "Krónan Public API", "source_url": BASE_URL + path,
            "query": query.strip(), "observed_at": observed_at,
            "availability_scope": "specific_store" if in_store else "home_delivery_selection",
            "availability_note": (
                "Krónan Scan & Go store catalog result; not a guaranteed shelf-stock check."
                if in_store else
                "Krónan home-delivery product selection; not store-specific availability."
            ),
            "store": store.strip() if in_store else None,
            "count": payload.get("count"), "page": payload.get("page", page),
            "page_count": payload.get("pageCount"),
            "has_next_page": payload.get("hasNextPage") is True, "items": hits,
        }

    async def scan_n_go_stores(self):
        """Return store IDs required by Krónan's physical-store catalog search."""
        payload = await self._list_request("GET", "/shopping-notes/scan-n-go-stores/")
        if not isinstance(payload, list):
            raise LookupFailure("search_failed")
        stores = []
        for item in payload:
            if (not isinstance(item, dict) or not isinstance(item.get("extId"), str)
                    or not isinstance(item.get("name"), str)):
                raise LookupFailure("search_failed")
            stores.append({"ext_id": item["extId"], "name": item["name"],
                           "source": "Krónan Public API"})
        return stores

    async def search_recipes(self, query="", page=1):
        if not isinstance(query, str) or len(query) > 64:
            raise ValueError("query must be a string up to 64 characters")
        if type(page) is not int or not 1 <= page <= 1000:
            raise ValueError("page must be an integer from 1 to 1000")
        payload = await self._list_request("POST", "/recipes/search/",
                                           json={"query": query, "page": page})
        if not isinstance(payload, dict) or not isinstance(payload.get("recipes"), list):
            raise LookupFailure("search_failed")
        rows = []
        for recipe in payload["recipes"]:
            if not isinstance(recipe, dict):
                raise LookupFailure("search_failed")
            row = {k: v for k, v in recipe.items() if k not in {"token", "favorited"}}
            rows.append(row)
        return {"source": "Krónan Public API", "source_url": BASE_URL + "/recipes/search/",
                "query": query, "page": page, "count": payload.get("count"),
                "recipes": rows, "available_tags": payload.get("availableTags", {})}

    async def recipe_detail(self, slug):
        if not isinstance(slug, str) or not slug or len(slug) > 128:
            raise ValueError("valid Krónan recipe slug required")
        if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in slug):
            raise ValueError("invalid Krónan recipe slug")
        payload = await self._list_request("GET", f"/recipes/{quote(slug, safe='')}/")
        if not isinstance(payload, dict) or payload.get("slug") != slug:
            raise LookupFailure("recipe_not_found")
        return {k: v for k, v in payload.items() if k != "token"}

    async def product_detail(self, sku):
        if not isinstance(sku, str) or not sku.strip() or len(sku) > 64:
            raise ValueError("valid Krónan SKU required")
        payload = await self._list_request("GET", f"/products/{quote(sku.strip(), safe='')}/")
        if not isinstance(payload, dict) or payload.get("sku") != sku.strip():
            raise LookupFailure("product_not_found")
        product = parse_product(payload)
        price = product.price_isk
        return {
            "provider": "kronan", "sku": product.sku, "name": product.name,
            "price_isk": price, "regular_price_isk": payload.get("price"),
            "on_sale": payload.get("onSale") is True,
            "price_info": payload.get("priceInfo"),
            "charged_by_weight": payload.get("chargedByWeight") is True,
            "price_per_kilo_isk": payload.get("pricePerKilo"),
            "base_comparison_unit": payload.get("baseComparisonUnit"),
            "quantity_per_base_comparison_unit": payload.get("qtyPerBaseCompUnit"),
            "quantity_in_sales_unit": payload.get("qtyInSalesUnit"),
            "temporary_shortage": payload.get("temporaryShortage") is True,
            "category_path": payload.get("categoryPath"),
            "brand": payload.get("brand"), "description": payload.get("description"),
            "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else [],
            "nutrition": payload.get("nutrition") if isinstance(payload.get("nutrition"), dict) else {},
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "Krónan Public API",
            "source_url": BASE_URL + f"/products/{quote(sku.strip(), safe='')}/",
        }

    async def quote_recipe(self, slug, portions, dietary_preferences=None):
        """Price Krónan-linked recipe SKUs as a preview; cannot establish full ingredient coverage."""
        try:
            portions = float(portions)
        except (TypeError, ValueError) as err:
            raise ValueError("portions must be positive") from err
        if not 0 < portions <= 100:
            raise ValueError("portions must be greater than 0 and at most 100")
        recipe = await self.recipe_detail(slug)
        servings = recipe.get("servings")
        if type(servings) not in (int, float) or servings <= 0:
            raise LookupFailure("recipe_invalid")
        product_quantities = {}
        for section, is_essential in (("items", False), ("essentials", True)):
            rows = recipe.get(section)
            if not isinstance(rows, list):
                raise LookupFailure("recipe_invalid")
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("product"), dict):
                    raise LookupFailure("recipe_invalid")
                product = row["product"]
                sku, quantity = product.get("sku"), row.get("quantity")
                if not isinstance(sku, str) or type(quantity) is not int or quantity < 1:
                    raise LookupFailure("recipe_invalid")
                entry = product_quantities.setdefault(sku, {"base_packages": 0, "essential": is_essential})
                entry["base_packages"] += quantity
                entry["essential"] = entry["essential"] and is_essential
        if not product_quantities:
            raise LookupFailure("recipe_unlinked")
        lines = []
        for sku, spec in product_quantities.items():
            exact_packages = spec["base_packages"] * portions / float(servings)
            packages = max(1, math.ceil(exact_packages))
            product = await self.product_detail(sku)
            lines.append({
                "sku": sku, "name": product["name"], "packages": packages,
                "base_recipe_packages": spec["base_packages"],
                "essential": spec["essential"], "unit_price_isk": product["price_isk"],
                "line_total_isk": product["price_isk"] * packages if product["price_isk"] is not None else None,
                "product": product,
            })
        dietary_conflicts = [conflict for line in lines
                            if (conflict := lactose_conflict(line["product"], dietary_preferences))]
        blocked = [line["sku"] for line in lines if line["product"]["temporary_shortage"]
                   or line["unit_price_isk"] is None]
        blocked.extend(item["sku"] for item in dietary_conflicts)
        total = None if blocked else sum(line["line_total_isk"] for line in lines)
        return {
            "title": recipe.get("displayName") or recipe.get("name"),
            "source": "Krónan recipe catalog", "source_slug": slug,
            "source_url": BASE_URL + f"/recipes/{quote(slug, safe='')}/",
            "portions": portions, "source_servings": servings,
            "scale_factor": round(portions / float(servings), 4),
            "preparation_minutes": recipe.get("preparationMinutes"),
            "cooking_minutes": recipe.get("cookingMinutes"),
            "difficulty": recipe.get("difficulty"), "ingredients_text": recipe.get("ingredients"),
            "instructions": recipe.get("directions"), "product_lines": lines,
            "blocked_skus": sorted(set(blocked)), "dietary_conflicts": dietary_conflicts,
            "verified_product_quote": not blocked, "complete": False, "saveable": False,
            "mapping_warning": "Krónan links these products to its recipe, but the linked list may omit ingredients from the recipe text. Audit every ingredient and build a mapped quote before saving.",
            "has_weight_priced_items": any(line["product"]["charged_by_weight"] for line in lines),
            "total_package_cost_isk": total,
            "cost_per_portion_isk": round(total / portions, 2) if total is not None else None,
            "price_observed_at": datetime.now(timezone.utc).isoformat(),
            "price_note": "Total is the full price to buy all listed packages; per-portion divides that basket by portions and does not deduct pantry stock or leftover package contents. Krónan catalog package prices may differ at checkout; weight-priced products are estimates.",
        }

    async def quote_generated_meal(self, title, portions, items, instructions="", source_url=None, dietary_preferences=None, ingredients=None):
        """Quote LLM-written recipe lines only after each selected SKU is re-read from Krónan."""
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("valid meal title required")
        try:
            portions = float(portions)
        except (TypeError, ValueError) as err:
            raise ValueError("portions must be positive") from err
        if not 0 < portions <= 100:
            raise ValueError("portions must be greater than 0 and at most 100")
        if not isinstance(ingredients, list) or not ingredients or len(ingredients) > 100:
            raise ValueError("provide the complete recipe ingredients as a list")
        required = [name.strip() for name in ingredients if isinstance(name, str) and name.strip() and len(name) <= 200]
        if len(required) != len(ingredients) or len({name.casefold() for name in required}) != len(required):
            raise ValueError("recipe ingredients must be non-empty, unique text")
        if not isinstance(items, list) or not items or len(items) > 100:
            raise ValueError("one to 100 ingredient product lines required")
        mapped = [item.get("ingredient", "").strip().casefold()
                  for item in items if isinstance(item, dict) and isinstance(item.get("ingredient"), str)]
        if len(mapped) != len(items) or len(set(mapped)) != len(items):
            raise ValueError("product lines must contain one mapping per recipe ingredient")
        if set(mapped) != {name.casefold() for name in required}:
            raise ValueError("product lines must map every declared recipe ingredient exactly once")
        lines = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("ingredient product lines must be objects")
            ingredient = item.get("ingredient")
            sku = item.get("sku")
            packages = item.get("packages")
            basis = item.get("quantity_basis", "")
            if not isinstance(ingredient, str) or not ingredient.strip() or len(ingredient) > 200:
                raise ValueError("each product line requires its recipe ingredient")
            ingredient = ingredient.strip()
            if not isinstance(sku, str) or not sku.strip() or type(packages) is not int or not 1 <= packages <= 100:
                raise ValueError("each product line requires a Krónan SKU and whole package count")
            if not isinstance(basis, str) or len(basis) > 500:
                raise ValueError("quantity_basis must be a short explanation")
            product = await self.product_detail(sku.strip())
            price = product["price_isk"]
            lines.append({
                "ingredient": ingredient.strip(), "quantity_basis": basis,
                "sku": product["sku"], "name": product["name"], "packages": packages,
                "unit_price_isk": price,
                "line_total_isk": price * packages if price is not None else None,
                "product": product,
            })
        dietary_conflicts = [conflict for line in lines
                            if (conflict := lactose_conflict(line["product"], dietary_preferences))]
        blocked = [line["sku"] for line in lines if line["product"]["temporary_shortage"]
                   or line["unit_price_isk"] is None]
        blocked.extend(item["sku"] for item in dietary_conflicts)
        total = None if blocked else sum(line["line_total_isk"] for line in lines)
        return {
            "title": title.strip(), "source": "LLM-generated recipe",
            "source_url": source_url, "portions": portions, "ingredients": required,
            "complete": not blocked, "saveable": not blocked,
            "mapping_warning": "Every declared recipe ingredient has an explicit Krónan SKU mapping; mapping semantics and package quantities are proposed by the LLM. Pantry sightings are advisory unless quantities are confirmed.",
            "ingredients_text": "\n".join(f"{line['ingredient']} — {line['packages']} × {line['name']} ({line['product'].get('price_info') or 'pack size not supplied'})" for line in lines),
            "instructions": instructions if isinstance(instructions, str) else "",
            "product_lines": lines, "blocked_skus": sorted(set(blocked)),
            "dietary_conflicts": dietary_conflicts, "complete": not blocked,
            "has_weight_priced_items": any(line["product"]["charged_by_weight"] for line in lines),
            "total_package_cost_isk": total,
            "cost_per_portion_isk": round(total / portions, 2) if total is not None else None,
            "price_observed_at": datetime.now(timezone.utc).isoformat(),
            "price_note": "Total is the full price to buy all listed packages; per-portion divides that basket by portions and does not deduct pantry stock or leftover package contents. Krónan prices re-read by SKU; checkout prices and weight-priced items can vary. Recipe/product pairing and package quantities were proposed by the LLM.",
        }

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
