"""Private Hermes MCP client for BurTracker's loopback-only Home Assistant API."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, timedelta
from pathlib import Path

import aiohttp
from mcp.server.fastmcp import FastMCP

HA_URL = os.environ.get("BURTRACKER_HA_URL", "http://127.0.0.1:8123").rstrip("/")
TOKEN_FILE = Path(os.environ.get(
    "BURTRACKER_AGENT_TOKEN_FILE", "/home/peturh/meal-planner/burtracker-agent-token"
)).resolve()

mcp = FastMCP("BurTracker household meal planner")


def _agent_token() -> str:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError as err:
        raise RuntimeError("Local BurTracker agent token is unavailable") from err
    if not token:
        raise RuntimeError("Local BurTracker agent token is empty")
    return token


async def _ha(method: str, action: str, *, args: dict | None = None) -> dict:
    headers = {"X-BurTracker-Agent": _agent_token()}
    timeout = aiohttp.ClientTimeout(total=75, connect=5)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        url = f"{HA_URL}/api/burtracker/meals/{action}"
        async with session.request(method, url, params=args if method == "GET" else None,
                                   json=args if method != "GET" else None) as response:
            try:
                payload = await response.json()
            except (ValueError, aiohttp.ContentTypeError) as err:
                raise RuntimeError(f"Home Assistant returned HTTP {response.status} with invalid JSON") from err
            if response.status >= 400:
                error = payload.get("error", "home_assistant_error") if isinstance(payload, dict) else "home_assistant_error"
                raise RuntimeError(f"BurTracker API {response.status}: {error}")
            return payload.get("result") if isinstance(payload, dict) and payload.get("ok") is True else payload


def _json(data):
    return json.dumps(data, ensure_ascii=False, default=str)


@mcp.tool()
async def get_meal_planning_context(start_date: str = "", end_date: str = "") -> str:
    """Read upcoming meals, household dietary constraints, feedback, pantry sightings, budget and calendar events.

    Call before planning. Pantry barcode sightings are not stock counts. Dietary and pregnancy
    preferences are not medical advice. Calendar results list the external HA calendars queried.
    """
    start = date.fromisoformat(start_date) if start_date else date.today()
    end = date.fromisoformat(end_date) if end_date else start + timedelta(days=6)
    if end < start or (end - start).days > 90:
        raise ValueError("Date range must be ordered and no longer than 90 days")
    start_text, end_text = start.isoformat(), end.isoformat()
    results = await asyncio.gather(
        _ha("GET", "settings"),
        _ha("GET", "meals", args={"start": start_text, "end": end_text}),
        _ha("GET", "feedback_history"),
        _ha("GET", "budget"),
        _ha("GET", "pantry"),
        _ha("GET", "calendar_events", args={"start": start_text, "end": end_text}),
    )
    meals = results[1]
    for meal in meals:
        meal["shopping_items"] = await _ha("GET", "shopping_items", args={"day": meal["day"]})
    return _json({
        "household_settings": results[0], "meals": meals,
        "feedback": results[2], "budget_targets": results[3],
        "pantry_observations_not_inventory": results[4],
        "calendar": results[5],
    })


@mcp.tool()
async def search_kronan_products(query: str, store_id: str = "", page: int = 1,
                                  page_size: int = 15) -> str:
    """Search Krónan catalog by name; returns real SKUs, current catalog price and pack data.

    Use store_id from list_kronan_stores for Scan & Go catalog search. Catalog search does not
    guarantee shelf stock. This operation is read-only and never changes a shopping list.
    """
    return _json(await _ha("POST", "kronan_search", args={
        "query": query, "store": store_id or None, "page": page, "page_size": page_size,
    }))


@mcp.tool()
async def list_kronan_stores() -> str:
    """List Krónan Scan & Go store IDs for store-scoped catalog searches."""
    return _json(await _ha("POST", "kronan_stores", args={}))


@mcp.tool()
async def search_kronan_recipes(query: str = "", page: int = 1) -> str:
    """Search Krónan's published recipes; inspect the ingredient text and product links before quoting."""
    return _json(await _ha("POST", "kronan_recipe_search", args={"query": query, "page": page}))


@mcp.tool()
async def get_kronan_recipe(slug: str) -> str:
    """Fetch an official Krónan recipe, directions and retailer-linked product list."""
    return _json(await _ha("POST", "kronan_recipe", args={"slug": slug}))


@mcp.tool()
async def quote_kronan_recipe(day: str, slug: str, portions: float) -> str:
    """Build a short-lived live-price quote for a Krónan recipe, without saving a meal.

    Prices and shortage status are re-read per SKU. Inspect the full recipe text against the
    retailer-linked list: this quote is not saveable if dietary constraints, prices, or mapping
    coverage are incomplete. Prices expire after two hours.
    """
    date.fromisoformat(day)
    return _json(await _ha("POST", "quote_kronan_recipe", args={
        "day": day, "slug": slug, "portions": portions,
    }))


@mcp.tool()
async def quote_generated_meal(day: str, title: str, portions: float,
                               product_lines_json: str, instructions: str,
                               source_url: str = "") -> str:
    """Price an LLM-written/adapted recipe only after every ingredient maps to a Krónan SKU.

    product_lines_json is a JSON array of {ingredient, sku, packages, quantity_basis}. Include
    every required purchase. The model chooses semantic matches and package counts; HA re-fetches
    each SKU's current Krónan details and blocks missing-price, shortage, or obvious non-lactose-free
    dairy items. The resulting package total includes whole packs, not inferred pantry stock.
    """
    date.fromisoformat(day)
    lines = json.loads(product_lines_json)
    if not isinstance(lines, list):
        raise ValueError("product_lines_json must be a JSON array")
    return _json(await _ha("POST", "quote_generated_meal", args={
        "day": day, "title": title, "portions": portions, "items": lines,
        "instructions": instructions, "source_url": source_url or None,
    }))


@mcp.tool()
async def assess_meal_budget(day: str, basket_cost_isk: int) -> str:
    """Compare a Krónan-priced whole-package meal basket with the configured weekly/monthly target.

    Returns actual grocery spend so far, remaining target, and the proposed basket verdict.
    If no budget is configured, it returns an empty assessments list; it will not invent a target.
    """
    date.fromisoformat(day)
    return _json(await _ha("GET", "budget_assessment", args={
        "day": day, "basket_cost_isk": basket_cost_isk,
    }))


@mcp.tool()
async def save_meal_quote(quote_id: str, replace_existing: bool = False) -> str:
    """Save a fresh complete Krónan quote as the dated meal with its auditable product list.

    Existing plans are protected unless replace_existing is explicitly true. Save retries are
    idempotent. Stale quotes must be repriced before saving.
    """
    return _json(await _ha("POST", "save_meal_quote", args={
        "quote_id": quote_id, "replace_existing": replace_existing,
    }))


@mcp.tool()
async def set_meal_status(day: str, status: str) -> str:
    """Record a meal outcome: cooked, not_home, ate_out, or cancelled."""
    date.fromisoformat(day)
    await _ha("POST", "set_status", args={"day": day, "status": status})
    return _json(await _ha("GET", "meals", args={"start": day, "end": day}))


@mcp.tool()
async def record_meal_feedback(day: str, metric: str, score: int, comment: str = "") -> str:
    """Save taste/enjoyment/difficulty/approval/portions/cost feedback against a dated dinner."""
    date.fromisoformat(day)
    await _ha("POST", "feedback", args={"day": day, "metric": metric,
                                         "score": score, "comment": comment})
    return _json(await _ha("GET", "feedback_history"))


@mcp.tool()
async def set_meal_budget(period: str, target_isk: int, effective_from: str = "") -> str:
    """Set or replace a confirmed weekly/monthly meal budget in ISK."""
    if effective_from:
        date.fromisoformat(effective_from)
    return _json(await _ha("POST", "add_budget", args={
        "period": period, "target_isk": target_isk, "effective_from": effective_from or None,
    }))


@mcp.tool()
async def set_household_dietary_preferences(preferences_json: str) -> str:
    """Update household dietary and food-safety preferences as JSON, without clinical claims."""
    value = json.loads(preferences_json)
    if not isinstance(value, dict):
        raise ValueError("preferences_json must contain a JSON object")
    return _json(await _ha("POST", "set_setting", args={
        "key": "household_dietary_preferences", "value": value,
    }))


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
