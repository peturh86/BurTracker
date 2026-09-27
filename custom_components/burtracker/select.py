"""Expose the BurTracker feedback metric selector."""
from .feedback_entities import select_entities


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(select_entities(entry))
