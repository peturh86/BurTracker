"""Portable shopping-list rules. No retailer or Home Assistant dependencies."""
from uuid import uuid4

NEEDS_ACTION = "needs_action"
COMPLETED = "completed"


def parse_trackers(value):
    """Accept a comma-separated list of exact ESPHome node names."""
    if not isinstance(value, str):
        raise ValueError("Tracker names must be text")
    names = {name.strip() for name in value.split(",") if name.strip()}
    if not names:
        raise ValueError("At least one tracker is required")
    return names


def validate_scan(data, trackers):
    """Reject unsupported events without converting barcodes to numbers."""
    if str(data.get("schema_version")) != "1":
        raise ValueError("Unsupported schema version")
    if data.get("intent") != "shopping":
        raise ValueError("Unsupported intent")
    tracker = data.get("tracker")
    if not isinstance(tracker, str) or tracker not in trackers:
        raise ValueError("Tracker is not enrolled")
    barcode = data.get("barcode")
    if (not isinstance(barcode, str) or not 1 <= len(barcode) <= 128
            or any(ord(char) < 32 or ord(char) == 127 for char in barcode)
            or not barcode.strip()):
        raise ValueError("Invalid barcode")
    return barcode, tracker


class ShoppingList:
    """JSON-serializable list, independent of transport and retailer lookup."""

    def __init__(self, items=None):
        self.items = items if items is not None else []

    def scan(self, barcode, tracker, timestamp):
        matches = [item for item in self.items if item.get("barcode") == barcode]
        active = next((item for item in matches if item["status"] == NEEDS_ACTION), None)
        if active is not None:
            return active["uid"], "already_present"
        if matches:
            item = matches[-1]
            item.update(status=NEEDS_ACTION, last_tracker=tracker, updated_at=timestamp)
            return item["uid"], "reopened"
        item = {
            "uid": uuid4().hex, "summary": f"Unresolved barcode: {barcode}",
            "status": NEEDS_ACTION, "barcode": barcode,
            "resolution": "unresolved", "last_tracker": tracker,
            "created_at": timestamp, "updated_at": timestamp,
        }
        self.items.append(item)
        return item["uid"], "added"

    def create(self, summary, timestamp):
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Item name must not be empty")
        item = {
            "uid": uuid4().hex, "summary": summary.strip(), "status": NEEDS_ACTION,
            "created_at": timestamp, "updated_at": timestamp,
        }
        self.items.append(item)
        return item["uid"]

    def update(self, uid, summary, status, timestamp):
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Item name must not be empty")
        if status not in (NEEDS_ACTION, COMPLETED):
            raise ValueError("Invalid item status")
        item = next((item for item in self.items if item["uid"] == uid), None)
        if item is None:
            raise ValueError("Item no longer exists")
        if status == NEEDS_ACTION and item.get("barcode") and any(
            other["uid"] != uid and other.get("barcode") == item["barcode"]
            and other["status"] == NEEDS_ACTION for other in self.items
        ):
            raise ValueError("This barcode already has an active item")
        item.update(summary=summary.strip(), status=status, updated_at=timestamp)

    def delete(self, uids):
        self.items = [item for item in self.items if item["uid"] not in uids]
