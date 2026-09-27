"""Meal quote persistence and save safety tests."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / "custom_components/burtracker/meals.py"
spec = importlib.util.spec_from_file_location("burtracker_meal_store_test", source)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


def quote(day="2026-09-28", title="Cod dinner"):
    lines = [
        {"ingredient": "cod", "sku": "sku-1", "name": "Cod 500 g", "packages": 2,
         "line_total_isk": 2400,
         "product": {"sku": "sku-1", "name": "Cod 500 g", "price_isk": 1200,
                     "price_info": "500 g", "observed_at": "2026-09-27T12:00:00+00:00",
                     "source_url": "https://api.kronan.is/api/v1/products/sku-1/",
                     "charged_by_weight": False, "temporary_shortage": False}},
    ]
    return {"day": day, "title": title, "portions": 3.5, "source_servings": 4,
            "source": "LLM-generated recipe", "source_url": None,
            "ingredients_text": "2 packages cod", "instructions": "Cook fully.",
            "product_lines": lines, "complete": True,
            "total_package_cost_isk": 2400, "cost_per_portion_isk": 685.71,
            "price_observed_at": "2026-09-27T12:00:00+00:00",
            "price_note": "Krónan catalog quote",
            "mapping_warning": "Each listed ingredient was mapped to a live Krónan product."}


class MealQuoteStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        store.DB = Path(self.temp.name) / "meals.db"
        store.init()

    def tearDown(self):
        self.temp.cleanup()

    def test_budget_assessment_uses_actual_purchases_not_planned_meals(self):
        store.add_budget("week", 10000, "2026-09-21")
        store.add_purchase(2500, "2026-09-22", "groceries")
        store.upsert_recipe("planned", 4, "x")
        store.upsert_meal("2026-09-23", "planned", 4, recipe_id=1, cost_isk=3000)
        result = store.budget_assessment("2026-09-24", 4000)["assessments"][0]
        self.assertEqual(result["actual_spend_isk"], 2500)
        self.assertEqual(result["planned_meals_isk"], 3000)
        self.assertEqual(result["remaining_isk"], 7500)
        self.assertTrue(result["within_target"])

    def test_budget_assessment_has_no_verdict_without_configured_target(self):
        self.assertEqual(store.budget_assessment("2026-09-28", 1000)["assessments"], [])

    def test_complete_quote_saves_meal_and_verified_product_lines(self):
        stored = store.create_quote(quote())
        result = store.commit_quote(stored["quote_id"])
        self.assertEqual(result["day"], "2026-09-28")
        self.assertEqual(result["cost_isk"], 2400)
        self.assertEqual(result["status"], "planned")
        products = store.meal_shopping_items("2026-09-28")
        self.assertEqual(products[0]["sku"], "sku-1")
        self.assertEqual(products[0]["packages"], 2)
        self.assertEqual(products[0]["line_total_isk"], 2400)
        self.assertEqual(store.meals("2026-09-28", "2026-09-28")[0]["title"], "Cod dinner")

    def test_save_retry_is_idempotent(self):
        stored = store.create_quote(quote())
        first = store.commit_quote(stored["quote_id"])
        second = store.commit_quote(stored["quote_id"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(store.meal_shopping_items("2026-09-28")), 1)

    def test_existing_day_requires_explicit_replacement(self):
        store.upsert_recipe("Old plan", 4, "ingredients")
        store.upsert_meal("2026-09-28", "Old plan", 3.5, recipe_id=1)
        stored = store.create_quote(quote())
        with self.assertRaisesRegex(ValueError, "replace_existing"):
            store.commit_quote(stored["quote_id"])
        result = store.commit_quote(stored["quote_id"], replace_existing=True)
        self.assertEqual(result["title"], "Cod dinner")
        self.assertEqual(result["cost_isk"], 2400)

    def test_incomplete_or_inconsistent_price_quote_is_rejected(self):
        incomplete = quote()
        incomplete["complete"] = False
        with self.assertRaises(ValueError):
            store.create_quote(incomplete)
        mismatched = quote()
        mismatched["product_lines"][0]["line_total_isk"] = 1
        with self.assertRaisesRegex(ValueError, "line total"):
            store.create_quote(mismatched)

    def test_missing_price_and_temporary_shortage_are_rejected(self):
        for field in ("price_isk", "temporary_shortage"):
            data = quote()
            if field == "price_isk":
                data["product_lines"][0]["product"][field] = None
            else:
                data["product_lines"][0]["product"][field] = True
            with self.assertRaises(ValueError):
                store.create_quote(data)

    def test_quote_expiry_prevents_saving_stale_catalog_prices(self):
        stored = store.create_quote(quote())
        with store.connect() as conn:
            conn.execute("UPDATE meal_quotes SET created_at=? WHERE id=?",
                         ("2020-01-01T00:00:00+00:00", stored["quote_id"]))
        with self.assertRaisesRegex(ValueError, "quote expired"):
            store.commit_quote(stored["quote_id"])
        self.assertEqual(store.meals("2026-09-28", "2026-09-28"), [])

    def test_feedback_metric_migration_preserves_rows_and_adds_enjoyment(self):
        store.upsert_recipe("Existing", 4, "x")
        store.upsert_meal("2026-09-27", "Existing", 2, recipe_id=1)
        with store.connect() as conn:
            conn.execute("ALTER TABLE feedback RENAME TO feedback_current")
            conn.execute("""CREATE TABLE feedback (
                id INTEGER PRIMARY KEY, meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
                metric TEXT NOT NULL CHECK(metric IN ('taste','difficulty','portions','approval','cost','other')),
                score INTEGER CHECK(score IS NULL OR score BETWEEN 1 AND 5),
                comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            conn.execute("INSERT INTO feedback(meal_id,metric,score,comment) VALUES(1,'taste',4,'kept')")
            conn.execute("DROP TABLE feedback_current")
        store.init()
        store.add_feedback("2026-09-27", "enjoyment", 5, "all liked it")
        with store.connect() as conn:
            rows = [tuple(r) for r in conn.execute("SELECT metric,score,comment FROM feedback ORDER BY id")]
        self.assertEqual(rows, [("taste", 4, "kept"), ("enjoyment", 5, "all liked it")])

    def test_household_constraints_default_without_overwriting_existing_settings(self):
        settings = store.get_settings()
        self.assertTrue(settings["household_dietary_preferences"]["lactose_free"])
        self.assertTrue(settings["household_dietary_preferences"]["pregnancy_food_safety"])
        self.assertTrue(settings["household_dietary_preferences"]["blood_sugar_consideration"])
        store.set_setting("household_dietary_preferences", {"lactose_free": True, "custom": "kept"})
        store.init()
        self.assertEqual(store.get_settings()["household_dietary_preferences"]["custom"], "kept")


if __name__ == "__main__":
    unittest.main()
