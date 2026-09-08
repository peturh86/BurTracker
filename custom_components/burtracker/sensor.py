"""Expose recorded spoilage reports without pretending to know quantities."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SpoilageReports(entry)])


class SpoilageReports(SensorEntity):
    _attr_name = "BurTracker Spoilage Reports"
    _attr_icon = "mdi:food-off"
    _attr_should_poll = False

    def __init__(self, entry):
        self.household = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_spoilage"

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(async_dispatcher_connect(
            self.hass, self.household.signal, self.async_write_ha_state
        ))

    @property
    def native_value(self):
        return len(self.household.model.spoiled)

    @property
    def extra_state_attributes(self):
        reports = self.household.model.spoiled
        return {"last_report": dict(reports[-1]) if reports else None}
