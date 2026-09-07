"""Set up one shared household list and select accepted tracker names."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import CONF_TRACKERS, DOMAIN
from .model import parse_trackers


def tracker_schema(default):
    return vol.Schema({vol.Required(CONF_TRACKERS, default=default): str})


class BurTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            try:
                names = parse_trackers(user_input[CONF_TRACKERS])
            except ValueError:
                errors["base"] = "invalid_trackers"
            else:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="BurTracker",
                    data={CONF_TRACKERS: ", ".join(sorted(names))},
                )
        return self.async_show_form(
            step_id="user", errors=errors,
            data_schema=tracker_schema(
                (user_input or {}).get(CONF_TRACKERS, "burtracker-hardware-test")
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BurTrackerOptionsFlow()


class BurTrackerOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                names = parse_trackers(user_input[CONF_TRACKERS])
            except ValueError:
                errors["base"] = "invalid_trackers"
            else:
                return self.async_create_entry(
                    title="", data={CONF_TRACKERS: ", ".join(sorted(names))}
                )
        default = self.config_entry.options.get(
            CONF_TRACKERS, self.config_entry.data[CONF_TRACKERS]
        )
        return self.async_show_form(
            step_id="init", errors=errors, data_schema=tracker_schema(
                (user_input or {}).get(CONF_TRACKERS, default)
            ),
        )
