"""Durable HA-triggered meal rerun request lifecycle tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / "custom_components/burtracker/meals.py"
spec = importlib.util.spec_from_file_location("burtracker_meal_rerun_store_test", source)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


class MealRerunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        store.DB = Path(self.temp.name) / "meals.db"
        store.init()

    def tearDown(self):
        self.temp.cleanup()

    def test_queued_request_can_complete_and_reads_back_compact_draft(self):
        request = store.create_meal_rerun("2026-09-30", "No tofu; lower cost")
        self.assertEqual(request["status"], "queued")
        self.assertEqual(request["reason"], "No tofu; lower cost")
        running = store.mark_meal_rerun_running(request["id"])
        self.assertEqual(running["status"], "running")
        draft = {
            "title": "Vegetable omelette", "portions": 4,
            "ingredients": ["eggs", "spinach"], "ingredients_text": "eggs\\nspinach",
            "instructions": "Cook", "total_package_cost_isk": 1400,
            "cost_per_portion_isk": 350, "price_observed_at": "2026-09-30T12:00:00+00:00",
            "product_lines": [{"ingredient": "eggs", "packages": 1, "sku": "eggs-1", "unit_price_isk": 500, "line_total_isk": 500,
                "product": {"provider": "kronan", "sku": "eggs-1", "name": "Eggs", "price_isk": 500, "temporary_shortage": False}},
             {"ingredient": "spinach", "packages": 1, "sku": "spinach-1", "unit_price_isk": 900, "line_total_isk": 900,
                "product": {"provider": "kronan", "sku": "spinach-1", "name": "Spinach", "price_isk": 900, "temporary_shortage": False}}],
        }

        result = store.finish_meal_rerun(request["id"], draft)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["result"], draft)
        self.assertEqual(store.latest_meal_rerun()["id"], request["id"])
        self.assertEqual(store.meals("2026-09-30", "2026-09-30"), [])

    def test_failed_request_is_visible_and_cannot_be_overwritten(self):
        request = store.create_meal_rerun("2026-09-30", "Try another")
        failed = store.finish_meal_rerun(request["id"], None, "webhook unavailable")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], "webhook unavailable")
        with self.assertRaisesRegex(LookupError, "already finished"):
            store.finish_meal_rerun(request["id"], {"title": "unexpected"})

    def test_unpriced_or_incomplete_candidate_cannot_complete(self):
        request = store.create_meal_rerun("2026-09-30", "Try another")
        store.mark_meal_rerun_running(request["id"])
        with self.assertRaisesRegex(ValueError, "complete recipe ingredient list"):
            store.finish_meal_rerun(request["id"], {"title": "Missing ingredients"})
        with self.assertRaisesRegex(ValueError, "one verified product line"):
            store.finish_meal_rerun(request["id"], {"title": "No quote", "portions": 4,
                "ingredients": ["yuca"], "ingredients_text": "yuca", "instructions": "cook", "product_lines": []})
        with self.assertRaisesRegex(ValueError, "priced Krónan product"):
            store.finish_meal_rerun(request["id"], {"title": "No price", "portions": 4,
                "ingredients": ["yuca"], "ingredients_text": "yuca", "instructions": "cook",
                "product_lines": [{"ingredient": "yuca", "packages": 1, "sku": "x", "unit_price_isk": None,
                    "line_total_isk": None, "product": {"provider": "kronan", "sku": "x", "name": "Yuca", "price_isk": None}}]})

    def test_rejected_suggestion_cannot_be_published_again(self):
        request = store.create_meal_rerun(
            "2026-09-30", "Try something else", "Tomato pasta", "tomato, pasta, basil"
        )
        store.mark_meal_rerun_running(request["id"])
        rejected_lines = [
            {"ingredient": name, "packages": 1, "sku": f"{name}-1", "unit_price_isk": 500, "line_total_isk": 500,
             "product": {"provider": "kronan", "sku": f"{name}-1", "name": name, "price_isk": 500, "temporary_shortage": False}}
            for name in ("tomato", "pasta", "basil")
        ]
        alternative_lines = [
            {"ingredient": name, "packages": 1, "sku": f"{name}-2", "unit_price_isk": 500, "line_total_isk": 500,
             "product": {"provider": "kronan", "sku": f"{name}-2", "name": name, "price_isk": 500, "temporary_shortage": False}}
            for name in ("chickpeas", "rice", "spinach")
        ]
        with self.assertRaisesRegex(ValueError, "different title"):
            store.finish_meal_rerun(request["id"], {
                "title": " Tomato Pasta ", "portions": 4,
                "ingredients": ["tomato", "pasta", "basil"], "ingredients_text": "tomato pasta basil",
                "instructions": "Cook", "product_lines": rejected_lines, "total_package_cost_isk": 1500,
            })
        with self.assertRaisesRegex(ValueError, "repeat the rejected ingredient list"):
            store.finish_meal_rerun(request["id"], {
                "title": "Baked tomato supper", "portions": 4,
                "ingredients": ["tomato", "pasta", "basil"], "ingredients_text": "tomato pasta basil",
                "instructions": "Cook", "product_lines": rejected_lines, "total_package_cost_isk": 1500,
            })
        accepted = store.finish_meal_rerun(request["id"], {
            "title": "Chickpea curry", "portions": 4,
            "ingredients": ["chickpeas", "rice", "spinach"], "ingredients_text": "chickpeas rice spinach",
            "instructions": "Cook", "product_lines": alternative_lines, "total_package_cost_isk": 1500,
        })
        self.assertEqual(accepted["status"], "complete")
        self.assertEqual(accepted["rejected_title"], "Tomato pasta")
        self.assertEqual(accepted["result"]["title"], "Chickpea curry")

    def test_init_migrates_existing_rerun_table(self):
        with store.connect() as conn:
            conn.execute("DROP TABLE meal_rerun_requests")
            conn.execute("""CREATE TABLE meal_rerun_requests (
                id TEXT PRIMARY KEY, planned_day TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL, result_json TEXT, error TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        store.init()
        with store.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(meal_rerun_requests)")}
        self.assertTrue({"rejected_title", "rejected_ingredients"}.issubset(columns))

    def test_invalid_date_and_reason_are_rejected(self):
        with self.assertRaises(ValueError):
            store.create_meal_rerun("not-a-date", "reason")
        with self.assertRaises(ValueError):
            store.create_meal_rerun("2026-09-30", "x" * 1001)


if __name__ == "__main__":
    unittest.main()
