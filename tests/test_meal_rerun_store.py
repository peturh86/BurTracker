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
        draft = {"title": "Vegetable omelette", "total_package_cost_isk": 1200,
                 "macros_per_portion": {"kcal": 440, "protein_g": 28}}
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

    def test_rejected_suggestion_cannot_be_published_again(self):
        request = store.create_meal_rerun(
            "2026-09-30", "Try something else", "Tomato pasta", "tomato, pasta, basil"
        )
        store.mark_meal_rerun_running(request["id"])
        with self.assertRaisesRegex(ValueError, "different title"):
            store.finish_meal_rerun(request["id"], {
                "title": " Tomato Pasta ", "ingredients_text": "different"
            })
        with self.assertRaisesRegex(ValueError, "repeat the rejected ingredient list"):
            store.finish_meal_rerun(request["id"], {
                "title": "Baked tomato supper", "ingredients_text": "tomato, pasta, basil"
            })
        accepted = store.finish_meal_rerun(request["id"], {
            "title": "Chickpea curry", "ingredients_text": "chickpeas, rice, spinach"
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
