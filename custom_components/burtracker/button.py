"""Provide the HA-native meal rerun controls."""
from .meal_rerun_entities import RequestMealRerun


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RequestMealRerun(entry)])
