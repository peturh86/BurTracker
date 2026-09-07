# Product definition

## Confirmed intent

- Low-effort barcode capture near where packaging is discarded.
- Shared shopping lists across multiple trackers in one home.
- ESP32-C6 target; Thread preferred.
- Home Assistant integration.
- Retailer integrations behind a strategy boundary; Krónan first.
- Insights into purchase habits and spoilage without requiring reliable inventory tracking.

## Proposed MVP behavior

A normal scan ensures the product is on the household's active shopping list. An existing entry stays at its current quantity unless the user explicitly requests more. This avoids routinely buying twice because two devices scanned the same packaging. Preserve both scan events for audit and undo.

Give immediate feedback for local capture, then distinct feedback for durable acceptance by the household service. Offline scans stay queued. Unknown barcodes still create an unresolved list entry for later naming. Manual list entry covers loose produce and unreadable packaging.

The household list is authoritative. Retailer cart export is a separate, visible operation. Checkout and payment are outside the MVP. A purchase-history import suggests which list entries were fulfilled; it must not erase a newer replenishment request blindly.

## Decisions still needed

| Decision | Why it matters | Proposed starting point |
| --- | --- | --- |
| Scan means add once or increment quantity? | Duplicate requests and household trust | Ensure present; explicit quantity editing |
| How is spoilage reported? | Discarded packaging does not establish waste | Optional action in UI; evaluate a button gesture later |
| HA required or optional? | Hosting, setup, support burden | Local service with HA as its first client; validate deployment choice |
| USB power or battery? | Scanner choice, enclosure, charging, wake latency | USB-powered bench prototype; battery target before custom PCB |
| Trigger button or automatic detection? | Convenience versus power and accidental scans | Compare both on real packaging |
| Main user interface? | Shopping away from home and household sharing | Mobile-friendly web UI, implementation undecided |
| Exact product or generic need? | Brand switching, pack sizes, unavailable goods | Preserve scanned identity; allow explicit substitutions |
| Cart synchronization policy? | External edits, duplicate quantities, availability | User-initiated export with reconciliation |
| Purchase-history coverage? | Cash, cards, other shops, multiple accounts | Show source and coverage; never imply all purchases are captured |
| Budget, size, batch quantity, battery runtime? | Sets practical hardware constraints | Establish targets before parts selection |
| Sharing and privacy? | Purchases reveal household behavior | Household access control, local storage, export and deletion |
| Intended distribution and licensing? | Hobby prototype versus supported product | Decide before public release |

## Measurement limits

Separate observed purchases, replenishment requests, explicitly reported waste, and estimates. Report purchase frequency and spending only over available history. Do not label unscanned goods as consumed, expired, or still present. Ordinary product identity alone does not provide an item's expiry date or remaining quantity.

## Experience to validate

Test with wet, curved, reflective, damaged, small, and chilled packaging; repeated scans; children or guests; muted feedback; multiple users; no internet; HA restart; and loss of the Thread border router. Evaluate whether the scan gesture is actually easier than remembering to add an item on a phone.
