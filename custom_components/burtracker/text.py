"""Expose the BurTracker feedback comment field."""
from .feedback_entities import text_entities


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(text_entities(entry))
