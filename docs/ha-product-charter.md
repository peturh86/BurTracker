# BurTracker: household groceries in Home Assistant

Status: product and interface proposal, 2026-09-07. This charter supersedes earlier proposals for optional HA, battery-powered trackers, and persistent offline scan queues.

## Product definition

BurTracker is a Home Assistant extension providing one place to manage a household's grocery purchases, shopping needs, reported consumption, and reported spoilage. Physical barcode trackers make recording events quick; retailer integrations supply product information and available purchase history. HA owns the data, business rules, retailer credentials, and user interface.

The tracker is an input and feedback device, not the entire product. The household can also manage groceries through HA without scanning a barcode. The system must remain useful when people miss scans or buy from unsupported retailers.

## Confirmed platform and prototype

- HA is mandatory. Multiple trackers serve one household.
- Final target: ESP32-C6, Thread preferred with Wi-Fi acceptable; exposed USB-C power, SSD1306 display, three buttons. Cable and external power supply are outside scope.
- Prototype: M5Stack Core2 plus Module13.2 QRCode, using ESPHome/Arduino with M5Stack libraries. UART uses Core2 RX13/TX14 at 115200 baud.
- User has demonstrated barcode capture and on-screen display. Scene-change triggering works but needs sensitivity/illumination tuning. HA connection and retailer lookup have not yet been demonstrated.
- Device operates online. No persistent offline scan queue is required. Show unavailable or uncertain status honestly.
- Barcode engine performs symbol decoding. No vision-model product recognition.
- Scanner procurement is reopened on cost. Earlier USD 49.90 GM65 selection is rejected; cheaper engines remain candidates pending quotation and testing.

## Grocery workflow

| Intent or source | Recorded fact | Default list effect |
| --- | --- | --- |
| Shopping-list scan | Household requests this product | Ensure an active entry exists; quantity policy remains proposed |
| Consumed scan | User reports consumption | None |
| Spoiled scan | User reports spoilage | None |
| Retailer purchase import | Provider reports a purchase | Reconcile against outstanding requests; preserve newer requests |
| Manual purchase entry | User reports a purchase elsewhere | Same reconciliation rules with manual provenance |
| Correction / undo | User corrects an earlier action | Apply targeted correction without deleting unrelated later work |

Shopping-list intent is the scanner default. Consumed/spoiled are explicit alternatives. Proposed one-shot intent selection returns to default after processing or inactivity. Exact button assignment remains a UX decision.

Repeated barcode readings from stationary packaging must be suppressed before creating business events. An intentional repeat scan must remain distinguishable from a transport retry. A three-second display cooldown in the current prototype is not a final business-event deduplication policy.

## Household view

Proposed dashboard sections:

1. Shopping: shared list, quantities, exact product matching, unresolved items, deliberate cart export.
2. Purchases: available receipts/purchase lines, prices actually paid, source account and store/channel coverage.
3. Consumption and waste: explicit reports, corrections, optional quantities/reasons, trends based on recorded data.
4. At home: recent purchases and estimated remaining groceries, clearly labeled as estimates with last evidence and correction controls.
5. Activity: combined chronological feed with source tracker/user/provider and undo where applicable.
6. Devices and connections: tracker health, retailer authentication, lookup failures, last successful import.

The first usable slice is Shopping plus Activity and a scanner price-lookup demonstration. Broader analytics follow verified history coverage and quantity semantics.

## Inventory and analytics limits

Do not present purchases minus scans as an exact stock count. A barcode identifies a product, not an individual package, expiry date, lot, or discarded fraction. A consumed/spoiled scan without a supplied quantity is a report with unknown quantity; it must not silently deduct a whole pack. Imported history may omit cash purchases, other retailers, or some accounts/channels.

Separate current catalog price from price actually paid. Display lookup time and provider context for catalog prices, and mark cached prices. Do not calculate monetary waste totals from unknown discarded quantities or silently value historic waste at today's catalog price.

## HA architecture

Use standard ESPHome native API connectivity for the physical trackers and a custom `burtracker` HA integration for household behavior. A custom device class or Matter endpoint is not required for the proposed ESPHome path. ESPHome project metadata identifies the firmware family/version; it does not install the BurTracker integration or create a grocery dashboard automatically.

Prototype onboarding: add the tracker using HA's ESPHome integration, install/configure BurTracker, and explicitly select the tracker devices to enroll. Automatic association can be added later after validating a supported discovery mechanism. Avoid duplicate connections to the same device and duplicate device-registry entries.

Expose a native HA to-do entity for the shared list where practical. Keep product IDs, quantities/units, provenance, and richer history in BurTracker storage, since the to-do contract does not supply a full grocery domain. Build the household dashboard over the integration's data; retain one authoritative list.

## Proposed device contract v1

ESPHome project identity: `burtracker.tracker`, with a real firmware version and unique per-device name. Hardware model remains distinguishable (Core2 prototype versus ESP32-C6 revision).

Scan messages are events, not merely changes to a last-barcode text sensor. Otherwise two intentional scans of the same code can disappear in state-based automations.

| Field | Meaning |
| --- | --- |
| schema_version | Integer contract version, initially 1 |
| request_id | Device boot/session identifier plus monotonically increasing scan sequence; unique across restarts |
| barcode | Raw barcode string preserving leading zeros |
| intent | shopping_list, consumed, or spoiled |
| device identity | Associated with the HA-enrolled source device; payload names are not authorization |

For the prototype, evaluate an `esphome.burtracker_scan` event via the native API. HA event access permission must be enabled for the selected ESPHome device. Bind source identity to enrollment and validate the payload; HA events are not an independently authenticated security boundary.

HA replies through an ESPHome user-defined API action with request ID, outcome, display name, barcode, and optional price/currency plus freshness. Device displays a reply only if its request ID matches the current request. Suggested outcomes: accepted, unknown_product, lookup_failed, rejected. Local decode success must be distinct from HA acceptance and successful retailer lookup.

Last barcode, selected mode, and connection status may additionally be entities for display/diagnostics. Do not create an entity per scan or grocery item. Device uptime and network diagnostics are useful; unrelated Core2 sensors are not part of the product interface.

## Retailer strategy

Keep the core independent of Krónan payloads. Each provider advertises supported capabilities: product/barcode lookup, current prices, purchase history, purchase statistics, cart reading/writing. Unsupported capabilities are explicit. Store account credentials in HA; scope mappings and imports to household/provider accounts.

First proof: barcode from tracker -> HA receives correlated request -> Krónan resolves exact product and applicable catalog price -> HA returns result to tracker. Unknown barcode and API failure are separate states. No cart mutation is needed for this demonstration. Purchase-history and cart integration follow authentication/schema verification.

## Next deliverables

- Consolidate the currently working ESPHome configuration, preserving asynchronous startup delays and stable scanner communications.
- Add Wi-Fi and encrypted native API, firmware metadata, event submission, and a correlated display-result action.
- Implement BurTracker's minimal HA setup/enrollment, event handler, durable list/activity records, and retailer strategy.
- Verify Krónan authentication and actual barcode/price response fields; use synthetic fixtures for tests.
- Demonstrate one scan event, repeated identical scans, unknown product, stale reply rejection, and visible HA/API failure handling.

## References checked

- [ESPHome in HA](https://www.home-assistant.io/integrations/esphome/)
- [ESPHome native API](https://esphome.io/components/api/)
- [ESPHome project metadata and sharing](https://esphome.io/guides/creators/)
- [HA to-do entity contract](https://developers.home-assistant.io/docs/core/entity/todo/)

This is a design charter, not evidence that the HA integration or retailer workflows are implemented.
