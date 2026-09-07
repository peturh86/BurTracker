# BurTracker: shopping list and Krónan product lookup

## Install or update

1. In HACS > Custom repositories add https://github.com/peturh86/BurTracker as Integration.
2. Download/update BurTracker to 0.2.0 and restart Home Assistant.
3. Under Settings > Devices & services, add BurTracker (or Configure the existing entry).
4. Enter exact ESPHome tracker names separated by commas, e.g. burtracker-hardware-test.
5. Enter your Krónan access token in the password field. An empty field retains the
   existing token. Tokens are kept in HA configuration, never in firmware.
6. Flash the updated m5stackcore2.yaml; preserve your local secrets.yaml.
7. Enable "Allow the device to perform Home Assistant actions" in the ESPHome device configuration.
8. Open To-do lists > BurTracker Shopping and scan a product.

HACS is usable with HA Container. If it is not installed, perform its one-time
installation into the persistent volume mapped to /config:
https://www.hacs.xyz/docs/use/download/download/

For manual installation, copy custom_components/burtracker into
/config/custom_components/burtracker and restart HA. The release ZIP includes that path.

## Krónan authentication

The public schema is accessible without credentials, but the product lookup requires
Authorization: AccessToken <token>. An unauthenticated live request was verified to
return 401 on 2026-09-07.

According to Krónan's API schema, access tokens are created in User or Customer group
settings and require an Auðkenni login. Enter only the token value in BurTracker.
Do not paste tokens into issue reports or chat.

Endpoint: GET https://api.kronan.is/api/v1/products/barcode/{barcode}/
Schema: https://api.kronan.is/api/v1/schema/
Interactive documentation: https://api.kronan.is/api/v1/schema/swagger-ui/

The endpoint directly returns PublicProductDetail. We use its name for the display
and retain its sku as the retailer product identity. We do not use fuzzy search or
guess the name from the barcode. The longer description field is not used as the
small-screen label.

## What happens on a scan

- The household list first durably ensures an entry exists for the scanned barcode.
- Krónan resolves the exact barcode. A match updates the unresolved list label and
  returns the product name to that scanner's screen.
- A manual list label is preserved. Product name and SKU are stored separately.
- A 404 stays unresolved. Authentication, rate limiting, and lookup failures are
  distinct from not found.
- Repeated scans keep one active entry. Completing then scanning reopens that entry.
- Deleting an item while a lookup is pending does not recreate it.
- Completing an item does not imply a purchase or alter inventory.
- Consumption/spoilage events remain unsupported and do not add shopping entries.

The provider uses an asynchronous HA HTTP session, a ten-second total lookup budget,
bounded in-memory cache (one hour for matches, one minute for misses), and backoff on
429. It only performs product GET requests. No checkout/cart writes, purchase import,
or price display is implemented.

## Firmware and feedback

Updated inbound event:

    schema_version: "1"
    tracker: burtracker-hardware-test
    barcode: "0012345678905"
    intent: shopping
    request_id: "<random-boot-session>-<scan-sequence>"

Old firmware without request_id can still populate/enrich the list, but cannot
receive correlated display feedback. Update both HA integration and firmware.

Firmware exposes an ESPHome action named burtracker_result with string fields
request_id, barcode, lookup_status, product_name. For the default tracker HA registers
esphome.burtracker_hardware_test_burtracker_result.

Replies are accepted only while waiting for the current request, with both request ID
and barcode matching. After 15 seconds the device shows "No HA reply / List status
unknown"; late replies are ignored. A decode alone is not displayed as a successful
list save. No offline queue/replay is implemented.

The HA event burtracker.scan_processed includes outcome, lookup_status, item_uid,
request_id, barcode, tracker, product_name. It is useful for diagnostics.
Lookup statuses: resolved, not_found, auth_required, rate_limited, lookup_failed,
item_removed. Storage failure is sent directly as save_failed to the display.

Tracker names are routing filters, not authentication. Other HA users/automations
with event-bus access can supply those names. Request IDs correlate display replies;
they do not provide persistent exactly-once processing.

## Storage and verification

HA Store data under .storage/burtracker.<entry_id> survives restart. Mutations are
serialized and only published after save succeeds. Removing the integration deletes
its storage. Firmware entities are separate from the BurTracker to-do entity.

Smoke test:
1. Configure a real token and scan a known Krónan product: list and display get a name.
2. Scan it again: one active list entry remains.
3. Scan two different products quickly: an older reply must not overwrite the latest.
4. Try an unknown barcode: an unresolved entry remains and display says not found.
5. Try without a token: display requests the token; it must not say product not found.
6. Complete, rename, rescan, and restart HA to verify persisted list behavior.

Tests use schema-shaped synthetic responses; no real token is available in the
development environment. Authenticated success, physical font rendering, and HA
action registration still need the live smoke test.

Run portable tests with python -m unittest discover -s tests -v (aiohttp required).
The provider strategy interface is in retailer.py; Krónan is its first implementation.
A future application/portal should reuse or migrate the grocery store rather than
maintain a second independent list.

## Build verification for 0.2.0

27 automated tests passed (provider, list model, and HA-boundary stand-ins).
The full Core2 firmware compiled successfully using ESPHome 2026.7.3 with dummy
credentials: application image approximately 1.54 MB, 18.9% of its flash partition.
The build uses the same YAML except substituted test credentials. This validates
compilation, not live network connectivity, authenticated API success, or physical
display rendering. No dummy-credential firmware binary is distributed.
