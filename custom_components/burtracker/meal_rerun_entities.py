"""HA-native controls to request and display a private Hermes meal rerun."""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path

from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.text import TextEntity, TextMode
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from . import meals
from .const import DOMAIN

RERUN_EVENT = "burtracker_meal_rerun_updated"
WEBHOOK_URL = os.environ.get(
    "BURTRACKER_HERMES_WEBHOOK_URL",
    "http://127.0.0.1:8644/webhooks/burtracker-meal-rerun",
)
TOKEN_FILE = os.environ.get(
    "BURTRACKER_AGENT_TOKEN_FILE", "/run/secrets/burtracker-agent-token"
)
SECRET_CONTEXT = b"burtracker-hermes-webhook-v3"


def _state(hass, entry_id):
    return hass.data.setdefault(DOMAIN, {}).setdefault(entry_id, {"rerun_reason": ""})


async def _webhook_secret():
    try:
        token = (await asyncio.to_thread(Path(TOKEN_FILE).read_text, encoding="utf-8")).strip()
    except OSError as err:
        raise RuntimeError("BurTracker agent token is unavailable") from err
    if not token:
        raise RuntimeError("BurTracker agent token is empty")
    return hmac.new(token.encode("utf-8"), SECRET_CONTEXT, hashlib.sha256).hexdigest()


class MealRerunReason(TextEntity):
    _attr_has_entity_name = False
    _attr_name = "BurTracker Meal Rerun Reason"
    _attr_icon = "mdi:comment-edit-outline"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = 1000
    _attr_should_poll = False

    def __init__(self, entry):
        self.entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_meal_rerun_reason"
        self._attr_native_value = ""

    async def async_set_value(self, value):
        self._attr_native_value = value[:1000]
        _state(self.hass, self.entry_id)["rerun_reason"] = self._attr_native_value
        self.async_write_ha_state()


class RequestMealRerun(ButtonEntity):
    _attr_has_entity_name = False
    _attr_name = "BurTracker Rerun Meal Suggestion"
    _attr_icon = "mdi:food-refresh"
    _attr_should_poll = False

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_meal_rerun"
        self._lock = asyncio.Lock()

    async def async_press(self):
        async with self._lock:
            day = dt_util.now().date().isoformat()
            reason = _state(self.hass, self.entry.entry_id).get("rerun_reason", "")
            prior = await asyncio.to_thread(meals.latest_meal_rerun)
            rejected = (prior.get("result") or {}) if prior and prior.get("planned_day") == day else {}
            if not rejected:
                plans = await asyncio.to_thread(meals.meals, day, day)
                if plans:
                    rejected = plans[0]
            rejected_title = rejected.get("title", "") if isinstance(rejected, dict) else ""
            rejected_ingredients = rejected.get("ingredients_text", rejected.get("ingredients", "")) if isinstance(rejected, dict) else ""
            if not isinstance(rejected_ingredients, str):
                rejected_ingredients = json.dumps(rejected_ingredients, ensure_ascii=False)
            row = await asyncio.to_thread(
                meals.create_meal_rerun, day, reason, rejected_title, rejected_ingredients
            )
            request_id = row["id"]
            self.hass.bus.async_fire(RERUN_EVENT, {"request_id": request_id})
            try:
                secret = await _webhook_secret()
                payload = {
                    "event_type": "meal_rerun",
                    "request_id": request_id,
                    "day": day,
                    "reason": reason,
                    "rejected_title": rejected_title,
                    "rejected_ingredients": rejected_ingredients,
                }
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                session = async_get_clientsession(self.hass)
                async with asyncio.timeout(12):
                    async with session.post(
                        WEBHOOK_URL,
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "X-Webhook-Signature": signature,
                            "X-Request-ID": request_id,
                        },
                    ) as response:
                        if response.status != 202:
                            raise RuntimeError(f"Hermes webhook returned HTTP {response.status}")
                self.hass.bus.async_fire(RERUN_EVENT, {"request_id": request_id})
            except Exception as err:
                await asyncio.to_thread(meals.finish_meal_rerun, request_id, None, str(err))
                self.hass.bus.async_fire(RERUN_EVENT, {"request_id": request_id})
                raise


class MealRerunStatus(SensorEntity):
    _attr_has_entity_name = False
    _attr_name = "BurTracker Meal Rerun"
    _attr_icon = "mdi:food-refresh"
    _attr_should_poll = False

    def __init__(self, entry):
        self._attr_unique_id = f"{entry.entry_id}_meal_rerun_status"
        self._row = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.hass.bus.async_listen(RERUN_EVENT, self._handle_event))
        await self.async_update()

    @callback
    def _handle_event(self, event):
        self.async_schedule_update_ha_state(True)

    async def async_update(self):
        self._row = await asyncio.to_thread(meals.latest_meal_rerun)

    @property
    def native_value(self):
        if not self._row:
            return "No rerun requested"
        result = self._row.get("result") or {}
        return result.get("title") or self._row.get("status", "unknown").replace("_", " ").title()

    @property
    def extra_state_attributes(self):
        if not self._row:
            return {}
        result = self._row.get("result") or {}
        return {
            "request_id": self._row.get("id"),
            "date": self._row.get("planned_day"),
            "status": self._row.get("status"),
            "reason": self._row.get("reason"),
            "rejected_title": self._row.get("rejected_title"),
            "error": self._row.get("error"),
            "draft": result,
            "updated_at": self._row.get("updated_at"),
        }


async def async_setup_entry(hass, entry, async_add_entities):
    _state(hass, entry.entry_id)
    async_add_entities([
        MealRerunReason(entry),
        RequestMealRerun(entry),
        MealRerunStatus(entry),
    ])
