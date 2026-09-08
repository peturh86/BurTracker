"""Test HA-boundary behavior with small in-memory stand-ins, not a real HA."""
import asyncio
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch


def load_household():
    modules = {}
    for name in (
        "homeassistant", "homeassistant.const", "homeassistant.core", "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client", "homeassistant.helpers.dispatcher",
        "homeassistant.helpers.storage", "homeassistant.util",
    ):
        modules[name] = types.ModuleType(name)
    modules["homeassistant.core"].callback = lambda f: f
    modules["homeassistant.const"].Platform = types.SimpleNamespace(TODO="todo", SENSOR="sensor")
    modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = Mock()
    modules["homeassistant.helpers.dispatcher"].async_dispatcher_send = Mock()
    modules["homeassistant.helpers.storage"].Store = Mock()
    modules["homeassistant.util"].dt = types.SimpleNamespace(utcnow=lambda: datetime.now(timezone.utc))
    modules["homeassistant.util"].slugify = lambda s: re.sub(r"[^a-z0-9_]", "_", s)
    base = Path(__file__).resolve().parents[1] / "custom_components/burtracker"
    spec = importlib.util.spec_from_file_location(
        "burtracker_boundary_test", base / "__init__.py",
        submodule_search_locations=[str(base)],
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules | {"burtracker_boundary_test": module}):
        spec.loader.exec_module(module)
    return module


module = load_household()


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        h = object.__new__(module.Household)
        h.hass = types.SimpleNamespace(services=types.SimpleNamespace(
            has_service=Mock(side_effect=lambda domain, action: not action.endswith("_v2")), async_call=AsyncMock(),
        ))
        h.hass.bus = types.SimpleNamespace(async_fire=Mock())
        h.trackers = {"kitchen", "bin"}
        product_class = module.KronanRetailer.lookup.__globals__["Product"]
        h.retailer = types.SimpleNamespace(lookup=AsyncMock(
            return_value=product_class("kronan", "sku-1", "Milk", 399)),
            add_to_shopping_list=AsyncMock(return_value="kronan_added"))
        h.latest_request = {"kitchen": "boot-2"}
        h.store = types.SimpleNamespace(async_save=AsyncMock())
        h.model = module.ShoppingList()
        h.lock = asyncio.Lock()
        h.signal = "updated"
        return h

    async def test_stale_or_legacy_reply_is_not_sent(self):
        h = self.make()
        for request in ("boot-1", ""):
            await h.async_reply("kitchen", "123", request, "resolved", "Milk")
        h.hass.services.async_call.assert_not_awaited()

    async def test_current_reply_routes_to_scanner_action(self):
        h = self.make()
        await h.async_reply("kitchen", "123", "boot-2", "resolved", "Milk")
        h.hass.services.async_call.assert_awaited_once_with(
            "esphome", "kitchen_burtracker_result", {
                "request_id": "boot-2", "barcode": "123",
                "lookup_status": "resolved", "product_name": "Milk",
            }, blocking=True)

    async def test_old_firmware_missing_action_is_tolerated(self):
        h = self.make()
        h.hass.services.has_service.side_effect = None
        h.hass.services.has_service.return_value = False
        await h.async_reply("kitchen", "123", "boot-2", "resolved", "Milk")
        h.hass.services.async_call.assert_not_awaited()

    async def test_failed_save_does_not_publish_memory(self):
        h = self.make()
        h.store.async_save.side_effect = OSError("disk full")
        with self.assertRaises(OSError):
            await h.async_mutate("scan", "00123", "kitchen", "t1")
        self.assertEqual(h.model.items, [])

    async def test_concurrent_scans_persist_one_item(self):
        h = self.make()
        results = await asyncio.gather(
            h.async_mutate("scan", "00123", "kitchen", "t1"),
            h.async_mutate("scan", "00123", "bin", "t1"),
        )
        self.assertEqual(len(h.model.items), 1)
        self.assertEqual({r[1] for r in results}, {"added", "already_present"})
        h.store.async_save.assert_awaited_once()

    async def test_price_mode_does_not_write_shopping_or_spoilage(self):
        h = self.make()
        await h.async_scan(types.SimpleNamespace(data={
            "schema_version": "1", "tracker": "kitchen", "barcode": "00123",
            "intent": "price", "request_id": "boot-3",
        }))
        h.store.async_save.assert_not_awaited()
        self.assertEqual(h.model.items, [])
        self.assertEqual(h.model.spoiled, [])
        event = h.hass.bus.async_fire.call_args.args[1]
        self.assertEqual(event["price_text"], "399 kr")
        self.assertEqual(event["outcome"], "lookup_only")

    async def test_spoilage_does_not_add_to_shopping_and_deduplicates_retry(self):
        h = self.make()
        event = types.SimpleNamespace(data={
            "schema_version": "1", "tracker": "kitchen", "barcode": "00123",
            "intent": "spoiled", "request_id": "boot-3",
        })
        await h.async_scan(event)
        await h.async_scan(event)
        self.assertEqual(h.model.items, [])
        self.assertEqual(len(h.model.spoiled), 1)
        self.assertIsNone(h.model.spoiled[0]["quantity"])
        self.assertEqual(h.model.spoiled[0]["product_name"], "Milk")

    async def test_new_reply_has_price_and_mode_outcome(self):
        h = self.make()
        h.hass.services.has_service.side_effect = None
        h.hass.services.has_service.return_value = True
        await h.async_reply("kitchen", "123", "boot-2", "resolved", "Milk",
                            "399 kr", "lookup_only")
        args = h.hass.services.async_call.call_args.args
        self.assertEqual(args[1], "kitchen_burtracker_result_v2")
        self.assertEqual(args[2]["price_text"], "399 kr")
        self.assertEqual(args[2]["outcome"], "lookup_only")


    async def test_shopping_match_goes_to_kronan_not_local_todo(self):
        h = self.make()
        await h.async_scan(types.SimpleNamespace(data={
            "schema_version": "1", "tracker": "kitchen", "barcode": "00123",
            "intent": "shopping", "request_id": "boot-3",
        }))
        h.retailer.add_to_shopping_list.assert_awaited_once()
        h.store.async_save.assert_not_awaited()
        self.assertEqual(h.model.items, [])
        self.assertEqual(h.hass.bus.async_fire.call_args.args[1]["outcome"], "kronan_added")

    async def test_unknown_shopping_scan_is_local_only(self):
        h = self.make()
        h.retailer.lookup.return_value = None
        await h.async_scan(types.SimpleNamespace(data={
            "schema_version": "1", "tracker": "kitchen", "barcode": "00123",
            "intent": "shopping", "request_id": "boot-3",
        }))
        h.retailer.add_to_shopping_list.assert_not_awaited()
        self.assertEqual(len(h.model.items), 1)
        self.assertEqual(h.hass.bus.async_fire.call_args.args[1]["outcome"], "unresolved")

    async def test_remote_failure_does_not_claim_added(self):
        h = self.make()
        h.retailer.add_to_shopping_list.side_effect = module.LookupFailure("write_uncertain")
        await h.async_scan(types.SimpleNamespace(data={
            "schema_version": "1", "tracker": "kitchen", "barcode": "00123",
            "intent": "shopping", "request_id": "boot-3",
        }))
        result = h.hass.bus.async_fire.call_args.args[1]
        self.assertEqual(result["outcome"], "unconfirmed")
        self.assertEqual(result["lookup_status"], "write_uncertain")
        self.assertEqual(h.model.items, [])


if __name__ == "__main__":
    unittest.main()
