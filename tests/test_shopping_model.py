"""Portable rule tests; run without installing Home Assistant."""
import importlib.util
import json
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components/burtracker/model.py"
spec = importlib.util.spec_from_file_location("burtracker_model", path)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class ShoppingTests(unittest.TestCase):
    def setUp(self):
        self.list = model.ShoppingList()
        self.event = dict(schema_version="1", tracker="kitchen",
                          barcode="0012345678905", intent="shopping")

    def test_current_firmware_contract_preserves_leading_zeros(self):
        self.assertEqual(model.validate_scan(self.event, {"kitchen"}),
                         ("0012345678905", "kitchen"))

    def test_reject_bad_payloads(self):
        changes = [
            {"schema_version": "2"}, {"intent": "consumed"},
            {"intent": "spoiled"}, {"tracker": "unknown"},
            {"barcode": 12345}, {"barcode": ""}, {"barcode": "   "},
            {"barcode": "abc\n"}, {"barcode": "x" * 129},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                model.validate_scan(self.event | change, {"kitchen"})

    def test_multiple_trackers_share_one_active_barcode(self):
        uid, outcome = self.list.scan("00123", "kitchen", "t1")
        self.assertEqual(outcome, "added")
        self.assertEqual(self.list.scan("00123", "bin", "t2"),
                         (uid, "already_present"))
        self.assertEqual(len(self.list.items), 1)

    def test_different_barcodes_remain_distinct(self):
        self.list.scan("00123", "kitchen", "t1")
        self.list.scan("123", "kitchen", "t2")
        self.assertEqual(len(self.list.items), 2)

    def test_complete_then_rescan_reopens_and_preserves_name(self):
        uid, _ = self.list.scan("00123", "kitchen", "t1")
        self.list.update(uid, "My milk", model.COMPLETED, "t2")
        self.assertEqual(self.list.scan("00123", "bin", "t3"), (uid, "reopened"))
        self.assertEqual(self.list.items[0]["summary"], "My milk")
        self.assertEqual(self.list.items[0]["resolution"], "unresolved")

    def test_state_round_trip_retains_deduplication(self):
        uid, _ = self.list.scan("00123", "kitchen", "t1")
        restored = model.ShoppingList(json.loads(json.dumps(self.list.items)))
        self.assertEqual(restored.scan("00123", "bin", "t2"),
                         (uid, "already_present"))

    def test_manual_item_can_be_edited_completed_and_deleted(self):
        uid = self.list.create("Bread", "t1")
        self.list.update(uid, "Wholemeal bread", model.COMPLETED, "t2")
        self.assertEqual(self.list.items[0]["status"], model.COMPLETED)
        self.list.delete([uid])
        self.assertEqual(self.list.items, [])

    def test_unknown_update_does_not_create_item(self):
        with self.assertRaises(ValueError):
            self.list.update("missing", "Bread", model.COMPLETED, "t1")
        self.assertEqual(self.list.items, [])

    def test_blank_manual_item_is_rejected(self):
        with self.assertRaises(ValueError):
            self.list.create("  ", "t1")

    def test_resolution_persists_provider_and_name(self):
        uid, _ = self.list.scan("00123", "kitchen", "t1")
        product = {"provider": "kronan", "sku": "77", "name": "Milk"}
        self.assertTrue(self.list.resolve(uid, product, "t2"))
        self.assertEqual(self.list.items[0]["summary"], "Milk")
        self.assertEqual(self.list.items[0]["sku"], "77")
        self.assertEqual(self.list.items[0]["barcode"], "00123")

    def test_resolution_preserves_manual_name(self):
        uid, _ = self.list.scan("00123", "kitchen", "t1")
        self.list.update(uid, "My milk", model.NEEDS_ACTION, "t2")
        self.list.resolve(uid, {"provider": "kronan", "sku": "77", "name": "Milk"}, "t3")
        self.assertEqual(self.list.items[0]["summary"], "My milk")

    def test_late_resolution_does_not_recreate_deleted_item(self):
        uid, _ = self.list.scan("00123", "kitchen", "t1")
        self.list.delete([uid])
        self.assertFalse(self.list.resolve(
            uid, {"provider": "kronan", "sku": "77", "name": "Milk"}, "t2"))
        self.assertEqual(self.list.items, [])

    def test_tracker_options(self):
        self.assertEqual(model.parse_trackers(" kitchen, bin, kitchen "),
                         {"kitchen", "bin"})
        with self.assertRaises(ValueError):
            model.parse_trackers(" , ")


if __name__ == "__main__":
    unittest.main()
