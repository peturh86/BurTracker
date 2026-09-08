# BurTracker setup (0.4.0)

## Install/update

1. Add https://github.com/peturh86/BurTracker in HACS Custom repositories, type Integration.
2. Download/update to 0.4.0 and restart Home Assistant.
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

The API's batch-add operation skips products already present, preserving their
quantities. Every shopping scan checks with Krónan; a local cache cannot suppress
re-adding an item that you removed from Krónan.

The device says success only after the API returns the SKU in the product list with
positive quantity. A timeout or ambiguous server response is unconfirmed, not success
or guaranteed failure. Check Krónan in that case. Retrying batch-add is safe for
existing quantities.

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
- POST /api/v1/product-lists/{token}/batch-add-items/ (skus: [resolved SKU])

Source: https://api.kronan.is/api/v1/schema/swagger-ui/#/product-lists
Machine schema: https://api.kronan.is/api/v1/schema/

## Device contract

Inbound event esphome.burtracker_scan:
schema_version: "1", tracker: exact node name, barcode: string preserving leading zeros,
intent: shopping/spoiled/price, request_id: random boot-session plus sequence.

Tracker names are routing filters, not authentication. The HA event bus is trusted.
Request IDs correlate display replies and deduplicate spoilage, not every external
effect across restarts.

HA calls esphome.<node>_burtracker_result_v2 with request_id, barcode, lookup_status,
product_name, price_text, outcome. The v0.2 action remains a fallback. New firmware
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
3. Scan again: its existing quantity is preserved.
4. Remove it in Krónan and scan again: it is re-added.
5. Yellow and red scans never add to Krónan.
6. An unknown barcode is kept locally, not posted to Krónan.
7. Restart HA: the same remote list is reused; local spoilage reports remain.

Release verification: 43 automated tests passed. Full Core2 compilation passed on
ESPHome 2026.7.3 using dummy credentials; authenticated remote writes remain untested.
