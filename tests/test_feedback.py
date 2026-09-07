"""Test HA-boundary behavior with small in-memory stand-ins, not a real HA."""
import asyncio
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
    modules["homeassistant.const"].Platform = types.SimpleNamespace(TODO="todo")
    modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = Mock()
    modules["homeassistant.helpers.dispatcher"].async_dispatcher_send = Mock()
    modules["homeassistant.helpers.storage"].Store = Mock()
    modules["homeassistant.util"].dt = types.SimpleNamespace()
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
            has_service=Mock(return_value=True), async_call=AsyncMock(),
        ))
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


if __name__ == "__main__":
    unittest.main()
