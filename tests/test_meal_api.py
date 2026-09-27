"""Tests for the narrow authenticated Home Assistant agent bridge."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from aiohttp import web

base = Path(__file__).resolve().parents[1] / "custom_components/burtracker"
package = types.ModuleType("burtracker_api_test")
package.__path__ = [str(base)]
sys.modules["burtracker_api_test"] = package

ha = types.ModuleType("homeassistant")
components = types.ModuleType("homeassistant.components")
http = types.ModuleType("homeassistant.components.http")
http.HomeAssistantView = type("HomeAssistantView", (), {"json": lambda self, data: web.json_response(data)})
http_const = types.ModuleType("homeassistant.components.http.const")
http_const.KEY_AUTHENTICATED = "authenticated"
http_const.KEY_HASS = "hass"
util = types.ModuleType("homeassistant.util")
util_dt = types.ModuleType("homeassistant.util.dt")
util_dt.as_local = lambda value: value
for name, module in {
    "homeassistant": ha,
    "homeassistant.components": components,
    "homeassistant.components.http": http,
    "homeassistant.components.http.const": http_const,
    "homeassistant.util": util,
    "homeassistant.util.dt": util_dt,
}.items():
    sys.modules[name] = module

meal_module = types.ModuleType("burtracker_api_test.meals")
meal_module.api_call = lambda action, **args: {"action": action, **args}
sys.modules[meal_module.__name__] = meal_module

spec = importlib.util.spec_from_file_location(
    "burtracker_api_test.api", base / "api.py"
)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)


class Request:
    def __init__(self, remote="127.0.0.1", headers=None, authenticated=False,
                 query=None, app=None, body=None):
        self.remote = remote
        self.headers = headers or {}
        self.query = query or {}
        self.app = app or {}
        self.body = body or {}
        self._auth = authenticated

    def get(self, key, default=None):
        return self._auth if key == "authenticated" else default

    async def json(self):
        return self.body


class ApiBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.token_path = Path(self.temp.name) / "agent-token"
        self.token_path.write_text("test-only-agent-token")
        self.old_env = os.environ.get("BURTRACKER_AGENT_TOKEN_FILE")
        os.environ["BURTRACKER_AGENT_TOKEN_FILE"] = str(self.token_path)
        self.view = api.MealPlannerView()

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop("BURTRACKER_AGENT_TOKEN_FILE", None)
        else:
            os.environ["BURTRACKER_AGENT_TOKEN_FILE"] = self.old_env
        self.temp.cleanup()

    async def test_agent_auth_requires_correct_token_and_loopback_peer(self):
        self.assertTrue(await api.MealPlannerView._authorized(Request(
            headers={"X-BurTracker-Agent": "test-only-agent-token"})))
        self.assertFalse(await api.MealPlannerView._authorized(Request(
            remote="192.168.1.24", headers={"X-BurTracker-Agent": "test-only-agent-token"})))
        self.assertFalse(await api.MealPlannerView._authorized(Request(
            headers={"X-BurTracker-Agent": "wrong"})))
        self.assertTrue(await api.MealPlannerView._authorized(Request(authenticated=True)))

    async def test_unauthorized_read_is_denied(self):
        response = await self.view.get(Request(remote="192.168.1.8"), "settings")
        self.assertEqual(response.status, 401)

    async def test_loopback_calendar_request_queries_external_ha_calendars(self):
        class States:
            def async_all(self, domain):
                self.domain = domain
                return [types.SimpleNamespace(entity_id="calendar.burtracker_meals"),
                        types.SimpleNamespace(entity_id="calendar.family")]
        class Services:
            async def async_call(self, domain, service, data, **kwargs):
                self.call = (domain, service, data, kwargs)
                return {"calendar.family": {"events": [{"summary": "Dentist"}]}}
        class Hass:
            states = States()
            services = Services()
        request = Request(headers={"X-BurTracker-Agent": "test-only-agent-token"},
                          query={"start": "2026-09-28", "end": "2026-09-28"},
                          app={"hass": Hass()})
        response = await self.view.get(request, "calendar_events")
        payload = json.loads(response.body)
        self.assertEqual(response.status, 200)
        self.assertEqual(payload["calendars"], ["calendar.family"])
        self.assertEqual(payload["events"]["calendar.family"]["events"][0]["summary"], "Dentist")
        domain, service, data, kwargs = request.app["hass"].services.call
        self.assertEqual((domain, service), ("calendar", "get_events"))
        self.assertEqual(data["entity_id"], ["calendar.family"])
        self.assertTrue(kwargs["return_response"])
        self.assertEqual(data["start_date_time"], "2026-09-28T00:00:00")

    async def test_empty_external_calendar_set_is_explicit(self):
        class Hass:
            class states:
                @staticmethod
                def async_all(domain):
                    return [types.SimpleNamespace(entity_id="calendar.burtracker_meals")]
        request = Request(headers={"X-BurTracker-Agent": "test-only-agent-token"},
                          query={"start": "2026-09-28", "end": "2026-09-28"},
                          app={"hass": Hass()})
        response = await self.view.get(request, "calendar_events")
        payload = json.loads(response.body)
        self.assertEqual(payload["calendars"], [])
        self.assertIn("No external", payload["note"])


if __name__ == "__main__":
    unittest.main()
