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
- POST /api/v1/products/search/ (query, page, pageSize, withDetail)
- POST /api/v1/shopping-notes/search/ (query, Scan & Go store ext_id)
- GET /api/v1/product-lists/ (limit/offset pagination)
- POST /api/v1/product-lists/ (name: HA)
- GET /api/v1/product-lists/{token}/
- POST /api/v1/product-lists/{token}/update-item/ (sku and absolute quantity)

BurTracker exposes a private agent API under `/api/burtracker/meals/{action}`. Normal Home Assistant-authenticated requests continue to work. The Hermes meal-planner MCP bridge uses a separate high-entropy token stored in a host-only mode-600 file; the Home Assistant container mounts that file read-only, and the agent API accepts that header only when the TCP peer is loopback. Do not proxy or expose this agent API to the LAN/Internet using the local token. The MCP server runs in the dedicated `meal-planner` Hermes profile and communicates with HA over `http://127.0.0.1:8123`; it never opens the SQLite database directly.

Supported agent operations:
- `POST /api/burtracker/meals/kronan_stores` — list store IDs.
- `POST /api/burtracker/meals/kronan_search` — body `{"query":"þorskur","page":1,"page_size":15}`; optional `store` uses Scan & Go search.
- `POST /api/burtracker/meals/kronan_recipe_search` — search official Krónan recipes.
- `POST /api/burtracker/meals/kronan_recipe` — fetch recipe by `slug`.
- `POST /api/burtracker/meals/quote_kronan_recipe` — preview current prices for Krónan-linked recipe SKUs. **Preview only:** it deliberately cannot be saved until the model audits recipe-text ingredients against linked products.
- `POST /api/burtracker/meals/quote_generated_meal` — verify each LLM-selected product SKU and price; body includes `day`, `title`, `portions`, `instructions`, optional `source_url`, and `items: [{"ingredient":"...","sku":"...","packages":1,"quantity_basis":"..."}]`. Every must-buy ingredient requires a product line. Whole packages are priced; incomplete, temporarily short, unpriced or obvious non-lactose-free dairy lines cannot produce a saveable quote.
- `POST /api/burtracker/meals/save_meal_quote` — body `{"quote_id":"..."}`; quote expires after two hours. Existing dated meals require explicit `replace_existing: true`; repeated saves are idempotent.
- `GET /api/burtracker/meals/calendar_events?start=YYYY-MM-DD&end=YYYY-MM-DD` — asks Home Assistant's calendar service for non-BurTracker calendars over the date range.

Quote totals are the full amount to buy all listed packages. “Per portion” divides that basket by planned portions; it does not infer household stock or subtract leftover package contents. Krónan home-delivery catalog search is not a physical-store shelf-stock guarantee, and variable-weight/checkout prices may differ. The agent does not automatically mutate Krónan lists.

## HA-triggered meal reruns

The rerun contract returns a **verified, purchasable quote as a draft**, not an unpriced candidate:

- The Hermes planner may make semantic product substitutions when the recipe still makes sense (e.g. any suitable spaghetti brand; another chicken cut when appropriate). It records the recipe ingredient, chosen Krónan product/SKU, quantity/package rationale, and explains meaningful substitutions.
- Every required recipe ingredient must map to a current, priced and non-short product. If no suitable mapping exists, the candidate is unobtainable: do not publish it; generate another candidate and repeat the matching/verification loop. Do not turn temporary Krónan errors (auth/rate-limit/network) into evidence of unavailability; fail the rerun clearly instead.
- Product search/catalog observations can guide idea generation, but the final chosen SKUs must be re-read before quoting. The callback rejects incomplete/unpriced quotes. The local catalog cache, if later added, is a candidate-generation aid only—not final availability evidence.
- Only after all lines verify should the model publish the compact quote/draft through `publish_meal_rerun_result`; HA re-reads each selected SKU through its own Krónan retailer, recomputes prices and availability, checks it is materially different from the rejected suggestion, stores only its own verified quote in the rerun record, and never commits it to the meal calendar. Existing date-based quote tools remain separate from the rerun callback.


The Hermes `meal-planner` profile must have webhook enabled on `127.0.0.1:8644`, and the `burtracker-meal-rerun` subscription must accept the `meal_rerun` event. The Home Assistant container uses host networking and the existing read-only `BURTRACKER_AGENT_TOKEN_FILE` mount; no extra port or secret mount is needed. Never put the agent token or webhook route secret in dashboard YAML or Git.

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

## 0.6.3 self-contained meal feedback

The BurTracker config entry creates native feedback controls: a metric selector,
1–5 score slider, and optional comment field. These are integration entities, not
`input_*` helpers, so no Home Assistant configuration YAML or script is required.
The dashboard's Save feedback button calls `burtracker.record_meal_feedback`,
which reads the current values from those entities. Enjoyment and cooking
difficulty are separate metrics; legacy `taste` entries remain accepted.

## Meal-planner slice (0.6.1)

BurTracker now owns the first durable meal-planner store in the HA config's `.storage/burtracker_meals.db`. It exposes a native meal calendar, a today's-meal sensor with recipe attributes, structured HA services (`burtracker.record_meal_feedback`, `burtracker.set_meal_status`), and an authenticated HA HTTP endpoint at `/api/burtracker/meals/{action}` for an external meal agent. Use the Home Assistant bearer-token API; never put that token in the integration or ESPHome firmware. The database stores recipes, planned meals, meal-specific feedback, pantry observations, actual purchase totals, weekly/monthly budget targets, and special-event allocations. Initial schema can be recreated during development; no migration system is included.

Default household settings are 2 adults, children aged 10 and 7, and a provisional 0.75 adult-equivalent serving for each child. This is a configurable starting estimate, not nutrition guidance; update it after portion feedback. New meal dates store one plan per day. `not_home` and `ate_out` are explicit outcomes.

The Core2's left SHOP tab now toggles to PANTRY when pressed again; tap it again to return to SHOP. PANTRY records one timestamped barcode sighting, looks up its product name if Krónan is available, and does not add to the Krónan shopping list or infer quantity. Replayed tracker/request IDs are deduplicated. Quantities remain unknown unless explicitly confirmed. Sightings include recent/aging/stale confidence (7/30-day thresholds), not assumed stock.

## HACS installation and usable meal dashboard

1. Update BurTracker through HACS and restart Home Assistant after the release is available.
2. Update firmware by copying `m5stackcore2.yaml` and `burtracker_ui.h` together into the ESPHome configuration directory beside your real `secrets.yaml`, then install/OTA flash the node. The Core2 left button toggles SHOP/PANTRY. The firmware is not installed by HACS.
3. The project dashboard YAML is a starter configuration, not automatically installed or updated by HACS. Merge `custom_components/burtracker/dashboard.yaml` into your dashboard's YAML source (or import it as a dashboard). It includes the rerun reason field, rejection button, result/status sensor, and draft details.
4. Use the integration's actual entity IDs: `calendar.burtracker_meals`, `sensor.today_s_meal`, `sensor.tomorrow_s_meal`, `sensor.pantry_barcode_observations`, `select.burtracker_feedback_metric`, `number.burtracker_feedback_score`, `text.burtracker_feedback_comment`, `text.burtracker_meal_rerun_reason`, `button.burtracker_rerun_meal_suggestion`, and `sensor.burtracker_meal_rerun`. Rerun controls are native BurTracker entities; no helper YAML or scripts are needed.
5. On the dinner card, review the draft, optionally enter a rerun reason, then press **Reject current suggestion & generate a different one**. It rejects the displayed draft (or today's saved dinner when no draft is displayed), requests another LLM-generated candidate, refreshes its Krónan products, and shows the draft without saving it. The server refuses the same title or exact ingredient list; the agent prompt also excludes the rejected meal and recipe.
6. Feedback and “not home” / “ate out” buttons are available directly on the dashboard. The feedback/status services default the date to today when omitted.

The API route is authenticated by Home Assistant. Examples:
- `GET /api/burtracker/meals/meals` (today through the next seven days by default)
- `GET /api/burtracker/meals/recipes`
- `POST /api/burtracker/meals/upsert_meal` with JSON `{"day":"YYYY-MM-DD","title":"Dinner","portions":3.5}`
- `POST /api/burtracker/meals/feedback` with JSON `{"day":"YYYY-MM-DD","metric":"portions","score":2,"comment":"Still too small"}`

Meal suggestions, automatic Krónan list synchronization, actual receipt import, calendar-aware LLM planning, and an agent-facing client are not wired yet. In particular, do not let the agent replay a shopping-list increment: the existing scanner semantics increment Krónan quantities. Add sync only after a read/compare/update strategy has been verified.


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
