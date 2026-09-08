# BurTracker setup (0.5.0)

## Install/update

1. Add https://github.com/peturh86/BurTracker in HACS Custom repositories, type Integration.
2. Download/update to 0.5.0 and restart Home Assistant.
3. Configure BurTracker with your exact ESPHome tracker names (comma-separated).
4. Enter your Krónan access token. Blank input preserves an existing token.
5. The integration finds a product list named exactly HA in that token's user/customer
   group. If absent after a complete search, it creates HA.
6. Place m5stackcore2.yaml and burtracker_ui.h together in the remote ESPHome
   configuration directory, alongside your existing secrets.yaml, and flash.
7. Enable "Allow the device to perform Home Assistant actions" for the ESPHome device.

The firmware source ZIP includes both firmware files and a secrets.example.yaml.
No real credentials or compiled firmware with dummy credentials are distributed.
HACS updates the integration, not firmware.

For HA Container, HACS installs into the persistent configuration volume mapped to
/config. Manual installation: copy custom_components/burtracker into
/config/custom_components/burtracker and restart.

## Shopping destination

Green Shopping resolves a barcode, then adds its SKU to the Krónan product list HA.
This is a product list, not the active checkout. No checkout/order/payment operations
are performed.

Each accepted Shopping scan increments the product quantity by one. The integration
reads the current remote list, then calls update-item with current quantity + 1.
All trackers in this integration share a lock, preventing lost increments between
their concurrent scans. The API exposes absolute quantity updates, not an atomic
increment: concurrent edits from the Krónan app or another HA installation can race
with this read/write operation.

A persistent request journal prevents the same tracker/request ID from incrementing
twice, including after HA restart. New request IDs represent new scans and increment
again. The journal records a pending write before issuing the POST. An ambiguous
write is never automatically replayed: check the Krónan list. A new intentional scan
will read the current quantity and add one more. Confirmed quantities are shown on
the device. The API's maximum quantity is 10,000.

The firmware's existing three-second repeat filter remains. A barcode continuously
presented and decoded can produce another accepted scan after that interval; this
is not guaranteed one-per-presentation detection. Remove it after the desired scan.

Initialization searches all returned pages before creation. Failed/incomplete searches
never trigger creation. Duplicate HA list names produce an explicit error instead of
choosing one arbitrarily. Rename the unwanted duplicate in Krónan and reload BurTracker.

List discovery/creation is serialized across trackers within this integration instance.
Separate HA installations can still race to create a list; Krónan's schema does not
document name uniqueness or a create idempotency key. The next discovery detects duplicates.

If initialization fails, the integration remains available for local reports and
price lookup; shopping scans retry discovery. A deleted cached list is invalidated
on 404 and rediscovered on the next shopping scan. Token changes reload the provider,
so a cached list from the prior account is not reused.

## Unresolved scans and existing local data

Unknown products cannot be added by SKU. They are preserved in the local
BurTracker Unresolved Scans to-do list for identification.

Previously recorded local shopping entries are preserved. This update does not
bulk-upload or delete them, and the local list is not a synchronized Krónan mirror.
Its entity ID may retain the old name, e.g. todo.burtracker_shopping.
Renaming or checking off local entries does not modify Krónan.

## Other modes and UI

Tabs align with the upside-down display's top button edge:
- Left green SHOP: physical C button, persistent selection.
- Center red SPOILED: physical B button, one report armed per press.
- Right yellow PRICE: physical A button, persistent selection.

Spoiled records an explicit report with unknown quantity and never adds to either
shopping list. Repeated transport requests with the same tracker/request ID are
deduplicated. Reports survive restart in HA storage. BurTracker Spoilage Reports
exposes the report count and last report; counts are not packages or units.
There is no inventory deduction, purchase inference, or waste-cost calculation.

Price only looks up the catalog product and changes no grocery records.
Displayed ISK values use discountedPrice when onSale is true, otherwise price.
Missing/invalid prices remain unavailable. Matches are cached for up to five minutes;
catalog prices are not a guarantee of checkout price.

## Authentication and API

The API schema is public; operations require Authorization: AccessToken <token>.
Krónan says access tokens are created in User/Customer group settings with an
Auðkenni login. Enter only the token value in HA. Tokens never enter firmware.

Endpoints used:
- GET /api/v1/products/barcode/{barcode}/
- GET /api/v1/product-lists/ (limit/offset pagination)
- POST /api/v1/product-lists/ (name: HA)
- GET /api/v1/product-lists/{token}/
- POST /api/v1/product-lists/{token}/update-item/ (sku and absolute quantity)

Source: https://api.kronan.is/api/v1/schema/swagger-ui/#/product-lists
Machine schema: https://api.kronan.is/api/v1/schema/

## Device contract

Inbound event esphome.burtracker_scan:
schema_version: "1", tracker: exact node name, barcode: string preserving leading zeros,
intent: shopping/spoiled/price, request_id: random boot-session plus sequence.

Tracker names are routing filters, not authentication. The HA event bus is trusted.
Request IDs correlate display replies and deduplicate spoilage and shopping writes.
Shopping requests without an ID are rejected; update firmware before using this release.

HA calls esphome.<node>_burtracker_result_v3 with request_id, barcode, lookup_status,
product_name, price_text, outcome, quantity_text. Earlier actions remain fallbacks. New firmware
waits 30 seconds, rejects replies for old requests/modes, and shows unknown status
after timeout. No offline queue or replay is implemented.

HA also emits burtracker.scan_processed for diagnostics, including lookup_status,
outcome and intent. Shopping outcomes include kronan_added, unresolved, not_added,
and unconfirmed. Initialization problems appear in HA logs.

## Verification

Run python -m unittest discover -s tests -v (aiohttp required). Tests simulate API
responses; no real retailer credentials are present in the development environment.

Live checks:
1. Configure a token: exactly one HA product list is found or created.
2. Scan a known product in green: it appears in Krónan HA, with its name on the device.
3. Scan again: quantity increases by one; confirm the resulting amount on screen.
4. Remove it in Krónan and scan again: it is re-added.
5. Yellow and red scans never add to Krónan.
6. An unknown barcode is kept locally, not posted to Krónan.
7. Restart HA: the same remote list is reused; local spoilage reports remain.

Release verification: 46 automated tests passed. Full Core2 compilation passed on
ESPHome 2026.7.3 using dummy credentials; authenticated remote writes remain untested.


## Simplified device UI (0.5.0)

The mode tabs are retained. The product card now fills the remaining screen height;
names use 32, 24, or 16 pixel text according to available space, wrap at words when
possible, and truncate only when the smallest size cannot fit. Prices and quantity
confirmation have their own rows. Repeated mode descriptions, the tiny footer, and
cache implementation details have been removed. The Spoiled rearm instruction is
kept in the readable status row.

The shopping request journal is stored in .storage/burtracker.<entry_id>.increments.
Removing the integration removes this journal too. Deleting it removes replay
protection for old request IDs. This is a request ledger, not purchase history.


### Display inactivity (0.5.1)

Results and errors clear after 15 seconds, returning to the selected mode's idle
screen. After 30 seconds without a barcode read, touch, or reply, the backlight
turns off. It stays lit while waiting for HA (up to the existing 30-second reply
timeout). A decoded barcode or touch wakes it immediately. The scanner library
exposes decoded results, not a separate scene-change event: moving an object
without decoding a barcode does not wake the display. Scanner monitoring, Wi-Fi,
HA and OTA remain running. This is backlight sleep, not ESP32 deep sleep.
Mode and spoilage rearming rules are preserved. Product name, price and status
are centered as a group, horizontally and vertically. Adjust RESULT_MS and
SLEEP_MS in burtracker_ui.h to change the durations.

### Battery expectations

M5Stack publishes approximately 5.09 V x 255.84 mA = 1.30 W for a powered
Module13.2 QRCode plus Core2. Its current Core2 specification lists 500 mAh at
3.7 V (1.85 Wh), giving about 1.4 hours before conversion losses at that measured
load. A 390 mAh battery would give about 1.1 hours before losses. These are
rough active-load estimates, not measured runtime for this firmware; scene-idle
consumption, battery age and backlight duty cycle matter. Check the actual battery
label and that the battery remains connected after stacking the module.

ESP32 deep sleep disconnects Wi-Fi and restarts firmware on wake. UART wake is a
light-sleep feature and can lose initial characters. Keeping the camera scanner
powered for scene detection still consumes power. For long battery life, a future
revision should switch off the scanner and use a low-power external presence
sensor or button to wake both scanner and host, allowing for startup and HA
reconnection time. USB power remains the practical choice for this prototype.

Sources: [Core2](https://docs.m5stack.com/en/core/core2),
[scanner power specifications](https://docs.m5stack.com/en/module/Module13.2_QRCode),
[scanner library](https://github.com/m5stack/M5Module-QRCode),
[ESP32 sleep modes](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/sleep_modes.html).
