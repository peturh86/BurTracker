"""The meal sensor platform exposes both today's and tomorrow's dinner."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from datetime import date, timedelta

base = Path(__file__).resolve().parents[1] / "custom_components/burtracker"
package = types.ModuleType("burtracker_sensor_test")
package.__path__ = [str(base)]
sys.modules[package.__name__] = package

ha = types.ModuleType("homeassistant")
components = types.ModuleType("homeassistant.components")
sensor_component = types.ModuleType("homeassistant.components.sensor")
sensor_component.SensorEntity = type("SensorEntity", (), {})
helpers = types.ModuleType("homeassistant.helpers")
dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
dispatcher.async_dispatcher_connect = lambda *args, **kwargs: (lambda: None)
for name, module in {
    "homeassistant": ha,
    "homeassistant.components": components,
    "homeassistant.components.sensor": sensor_component,
    "homeassistant.helpers": helpers,
    "homeassistant.helpers.dispatcher": dispatcher,
}.items():
    sys.modules[name] = module

spec = importlib.util.spec_from_file_location(
    "burtracker_sensor_test.sensor", base / "sensor.py"
)
sensor_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sensor_module
spec.loader.exec_module(sensor_module)
store = importlib.import_module("burtracker_sensor_test.meals")


class MealSensorTests(unittest.IsolatedAsyncioTestCase):
    async def test_tomorrow_entity_is_added_and_reads_tomorrow_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            store.DB = Path(tmp) / "meals.db"
            store.init()
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            store.upsert_recipe("Cod", 4, "Fish, vegetables", "Roast")
            store.upsert_meal(tomorrow, "Cod dinner", 3.5, recipe_id=1, cost_isk=3400)
            entry = types.SimpleNamespace(
                entry_id="entry", runtime_data=types.SimpleNamespace(model=types.SimpleNamespace(spoiled=[],items=[]),signal="s")
            )
            added=[]
            def add_entities(entities): added.extend(entities)
            await sensor_module.async_setup_entry(None, entry, add_entities)
            tomorrow_entity=next(x for x in added if isinstance(x,sensor_module.TomorrowMeal))
            self.assertEqual(tomorrow_entity._attr_unique_id,"entry_tomorrow_meal")
            self.assertEqual(tomorrow_entity._attr_name,"Tomorrow's Meal")
            self.assertEqual(tomorrow_entity.native_value,"Cod dinner")
            attrs=tomorrow_entity.extra_state_attributes
            self.assertEqual(attrs["day"],tomorrow)
            self.assertEqual(attrs["cost_isk"],3400)
            self.assertEqual(attrs["shopping_items"],[])


if __name__ == "__main__":
    unittest.main()
