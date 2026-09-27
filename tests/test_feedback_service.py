"""Verify the Lovelace no-payload feedback action reads BurTracker entities."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from datetime import date
from unittest.mock import Mock, patch


BASE = Path(__file__).resolve().parents[1] / "custom_components/burtracker"


def load_service_module():
    package_name = "burtracker_service_test"
    package = types.ModuleType(package_name)
    package.__path__ = [str(BASE)]
    const = types.ModuleType(f"{package_name}.const")
    const.DOMAIN = "burtracker"
    const.RESULT_EVENT = "burtracker.meal_result"
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    core.ServiceCall = object
    helpers = types.ModuleType("homeassistant.helpers")
    validation = types.ModuleType("homeassistant.helpers.config_validation")
    validation.date = lambda value: value
    validation.string = str
    modules = {
        package_name: package,
        f"{package_name}.const": const,
        "homeassistant": ha,
        "homeassistant.core": core,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.config_validation": validation,
    }
    spec = importlib.util.spec_from_file_location(
        f"{package_name}.services", BASE / "services.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules | {spec.name: module}):
        spec.loader.exec_module(module)
    return module


services_module = load_service_module()


class FeedbackServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registered = {}
        self.states = {
            "select.burtracker_feedback_metric": types.SimpleNamespace(state="difficulty"),
            "number.burtracker_feedback_score": types.SimpleNamespace(state="2"),
            "text.burtracker_feedback_comment": types.SimpleNamespace(state="Too difficult after work"),
        }
        self.hass = types.SimpleNamespace(
            services=types.SimpleNamespace(async_register=self._register),
            states=types.SimpleNamespace(get=self.states.get),
            bus=types.SimpleNamespace(async_fire=Mock()),
        )
        self.store = types.SimpleNamespace(add_feedback=Mock(), set_status=Mock())
        services_module.register_meal_services(self.hass, self.store)

    def _register(self, domain, name, handler, schema):
        self.registered[name] = (handler, schema)

    async def test_dashboard_service_reads_current_native_entities(self):
        handler, schema = self.registered["record_meal_feedback"]
        self.assertEqual(schema({}), {})
        await handler(types.SimpleNamespace(data={}))
        self.store.add_feedback.assert_called_once_with(
            date.today().isoformat(), "difficulty", 2, "Too difficult after work"
        )
        self.hass.bus.async_fire.assert_called_once()

    async def test_explicit_service_values_override_entity_states(self):
        handler, _ = self.registered["record_meal_feedback"]
        await handler(types.SimpleNamespace(data={
            "day": "2026-09-28", "metric": "enjoyment", "score": 5, "comment": "Loved it",
        }))
        self.store.add_feedback.assert_called_once_with("2026-09-28", "enjoyment", 5, "Loved it")

    async def test_missing_score_control_fails_clearly(self):
        handler, _ = self.registered["record_meal_feedback"]
        self.states.pop("number.burtracker_feedback_score")
        with self.assertRaises(services_module.HomeAssistantError):
            await handler(types.SimpleNamespace(data={}))
        self.store.add_feedback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
