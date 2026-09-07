"""Receive ESPHome shopping scans and persist the household list."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import logging

from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .const import CONF_TRACKERS, DOMAIN, RESULT_EVENT, SCAN_EVENT
from .kronan import KronanRetailer
from .retailer import LookupFailure
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
        token = entry.options.get("kronan_token", entry.data.get("kronan_token", ""))
        self.retailer = KronanRetailer(async_get_clientsession(hass), token)
        self.latest_request = {}
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

    async def async_reply(self, tracker, barcode, request_id, status, name=""):
        """Use the existing ESPHome connection, with no additional API client."""
        if not request_id or self.latest_request.get(tracker) != request_id:
            return
        action = slugify(f"{tracker}_burtracker_result")
        if not self.hass.services.has_service("esphome", action):
            _LOGGER.debug("Tracker feedback action unavailable: %s", action)
            return
        try:
            await self.hass.services.async_call("esphome", action, {
                "request_id": request_id, "barcode": barcode,
                "lookup_status": status, "product_name": name,
            }, blocking=True)
        except Exception:
            _LOGGER.warning("Could not deliver tracker feedback to %s", tracker)

    async def async_scan(self, event):
        try:
            barcode, tracker = validate_scan(event.data, self.trackers)
        except ValueError as err:
            _LOGGER.debug("Ignoring scan: %s", err)
            return
        request_id = event.data.get("request_id", "")
        if not isinstance(request_id, str) or len(request_id) > 128:
            _LOGGER.debug("Ignoring scan with invalid request ID")
            return
        self.latest_request[tracker] = request_id
        try:
            uid, outcome = await self.async_mutate(
                "scan", barcode, tracker, dt_util.utcnow().isoformat()
            )
        except Exception:
            _LOGGER.exception("Could not persist shopping scan")
            await self.async_reply(tracker, barcode, request_id, "save_failed")
            return

        name = ""
        try:
            product = await self.retailer.lookup(barcode)
            if product is None:
                status = "not_found"
            else:
                saved = await self.async_mutate(
                    "resolve", uid, asdict(product), dt_util.utcnow().isoformat()
                )
                status = "resolved" if saved else "item_removed"
                name = product.name if saved else ""
        except LookupFailure as err:
            status = err.status
        except Exception:
            _LOGGER.exception("Could not enrich shopping item")
            status = "lookup_failed"

        self.hass.bus.async_fire(RESULT_EVENT, {
            "tracker": tracker, "barcode": barcode, "request_id": request_id,
            "outcome": outcome, "item_uid": uid,
            "lookup_status": status, "product_name": name,
        })
        await self.async_reply(tracker, barcode, request_id, status, name)


async def async_setup_entry(hass, entry):
    household = Household(hass, entry)
    await household.async_load()
    entry.runtime_data = household
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    @callback
    def handle_scan(event):
        # Config-entry tasks are cancelled on unload/reload, avoiding stale writers.
        entry.async_create_background_task(
            hass, household.async_scan(event), "BurTracker barcode lookup"
        )

    entry.async_on_unload(hass.bus.async_listen(SCAN_EVENT, handle_scan))
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass, entry):
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_remove()
