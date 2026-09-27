"""Expose the BurTracker feedback score control."""
from .feedback_entities import number_entities


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(number_entities(entry))
