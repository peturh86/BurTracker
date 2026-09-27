"""Register structured meal-planning actions in Home Assistant."""
from datetime import date
import voluptuous as vol
from homeassistant.core import HomeAssistant, HomeAssistantError, ServiceCall
from homeassistant.helpers import config_validation as cv
from .const import DOMAIN, RESULT_EVENT


def register_meal_services(hass: HomeAssistant, meal_store) -> None:
    feedback_schema = vol.Schema({
        vol.Optional("day"): cv.date,
        vol.Optional("metric"): vol.In({"enjoyment", "taste", "difficulty", "portions", "approval", "cost", "other"}),
        vol.Optional("score"): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
        vol.Optional("comment"): cv.string,
    })
    status_schema = vol.Schema({
        vol.Optional("day"): cv.date,
        vol.Required("status"): vol.In({"cooked", "not_home", "ate_out", "cancelled"}),
    })

    async def record_feedback(call: ServiceCall) -> None:
        day = str(call.data.get("day", date.today()))
        metric = call.data.get("metric")
        if metric is None:
            state = hass.states.get("select.burtracker_feedback_metric")
            metric = state.state if state is not None else None
        score = call.data.get("score")
        if score is None:
            state = hass.states.get("number.burtracker_feedback_score")
            score = state.state if state is not None else None
        comment = call.data.get("comment")
        if comment is None:
            state = hass.states.get("text.burtracker_feedback_comment")
            comment = state.state if state is not None else ""
        if metric is None or score is None:
            raise HomeAssistantError(
                "BurTracker feedback controls are not ready; reload the integration and try again."
            )
        try:
            score_value = float(score)
            if not score_value.is_integer() or not 1 <= score_value <= 5:
                raise ValueError("score out of range")
            score = int(score_value)
        except (TypeError, ValueError) as err:
            raise HomeAssistantError("BurTracker feedback score must be a whole number from 1 to 5.") from err
        meal_store.add_feedback(day, metric, score, comment)
        hass.bus.async_fire(RESULT_EVENT, {
            "type": "meal_feedback_saved", "day": day,
            "metric": metric, "score": score,
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
