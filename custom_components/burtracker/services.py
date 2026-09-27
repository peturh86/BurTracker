"""Register structured meal-planning actions in Home Assistant."""
from datetime import date
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN, RESULT_EVENT


def register_meal_services(hass: HomeAssistant, meal_store) -> None:
    feedback_schema = vol.Schema({
        vol.Optional("day"): cv.date,
        vol.Required("metric"): vol.In({"enjoyment", "taste", "difficulty", "portions", "approval", "cost", "other"}),
        vol.Optional("score"): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
        vol.Optional("comment", default=""): cv.string,
    })
    status_schema = vol.Schema({
        vol.Optional("day"): cv.date,
        vol.Required("status"): vol.In({"cooked", "not_home", "ate_out", "cancelled"}),
    })

    async def record_feedback(call: ServiceCall) -> None:
        day = str(call.data.get("day", date.today()))
        meal_store.add_feedback(
            day, call.data["metric"], call.data.get("score"),
            call.data.get("comment", ""),
        )
        hass.bus.async_fire(RESULT_EVENT, {
            "type": "meal_feedback_saved", "day": day,
        })

    async def set_status(call: ServiceCall) -> None:
        day = str(call.data.get("day", date.today()))
        meal_store.set_status(day, call.data["status"])
        hass.bus.async_fire(RESULT_EVENT, {
            "type": "meal_status_changed", "day": day,
            "status": call.data["status"],
        })

    hass.services.async_register(
        DOMAIN, "record_meal_feedback", record_feedback, schema=feedback_schema,
    )
    hass.services.async_register(
        DOMAIN, "set_meal_status", set_status, schema=status_schema,
    )
