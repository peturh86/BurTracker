"""Receive ESPHome shopping scans and persist the household list."""
import asyncio
from copy import deepcopy
import logging

from homeassistant.const import Platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_TRACKERS, DOMAIN, RESULT_EVENT, SCAN_EVENT
from .model import ShoppingList, parse_trackers, validate_scan

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.TODO]


class Household:
    """Serialize mutations and publish only successfully persisted state."""

    def __init__(self, hass, entry):
        self.hass = hass
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.signal = f"{DOMAIN}_{entry.entry_id}_updated"
        self.lock = asyncio.Lock()
        self.model = ShoppingList()
        self.trackers = parse_trackers(
            entry.options.get(CONF_TRACKERS, entry.data[CONF_TRACKERS])
        )

    async def async_load(self):
        data = await self.store.async_load()
        if data is not None:
            self.model = ShoppingList(data["items"])

    async def async_mutate(self, method, *args):
        async with self.lock:
            candidate = ShoppingList(deepcopy(self.model.items))
            result = getattr(candidate, method)(*args)
            if candidate.items != self.model.items:
                await self.store.async_save({"items": candidate.items})
                self.model = candidate
                async_dispatcher_send(self.hass, self.signal)
            return result

    async def async_scan(self, event):
        try:
            barcode, tracker = validate_scan(event.data, self.trackers)
        except ValueError as err:
            _LOGGER.debug("Ignoring scan: %s", err)
            return
        try:
            uid, outcome = await self.async_mutate(
                "scan", barcode, tracker, dt_util.utcnow().isoformat()
            )
        except Exception:
            _LOGGER.exception("Could not persist shopping scan")
            self.hass.bus.async_fire(RESULT_EVENT, {
                "tracker": tracker, "barcode": barcode, "outcome": "save_failed",
            })
            return
        self.hass.bus.async_fire(RESULT_EVENT, {
            "tracker": tracker, "barcode": barcode,
            "outcome": outcome, "item_uid": uid,
        })


async def async_setup_entry(hass, entry):
    household = Household(hass, entry)
    await household.async_load()
    entry.runtime_data = household
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(hass.bus.async_listen(SCAN_EVENT, household.async_scan))
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass, entry):
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
