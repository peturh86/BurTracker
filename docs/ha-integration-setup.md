# BurTracker HA integration: first shopping slice

## What is implemented

A custom integration consumes the existing ESPHome event and maintains one persistent
household list exposed through a native HA to-do entity, normally
`todo.burtracker_shopping`. HA may choose another entity ID if that ID already exists.
No separate automation is required. Multiple configured tracker names feed this list.

The list is stored using HA's Store helper under `.storage/burtracker.<entry_id>`.
It survives restarts. Writes are serialized; memory and entity updates occur only
after a successful save. Removing the integration deletes its storage.

This is the initial HA-hosted backend. A future BurTracker application/portal should
reuse or migrate this data behind a service boundary rather than maintain a second list.

## Install through HACS

HACS works with Home Assistant Container; it is a custom integration, not a
Supervisor app. If HACS is already installed:

1. Open HACS > three-dot menu > Custom repositories.
2. Enter https://github.com/peturh86/BurTracker and choose Integration.
3. Download BurTracker, then restart Home Assistant.
4. Add BurTracker under Settings > Devices & services and configure tracker names.
5. Open To-do lists > BurTracker Shopping.

HACS requires a public GitHub repository. A default-store listing is not required.

If HACS is not installed yet, it needs a one-time installation into HA's persistent
configuration volume. For Docker, use the host directory/volume mapped to /config,
not a temporary container filesystem. Follow https://www.hacs.xyz/docs/use/download/download/
and then https://www.hacs.xyz/docs/use/configuration/basic/ .

## Manual install

1. Copy the entire `custom_components/burtracker` folder from this repository into
   your HA configuration directory as `/config/custom_components/burtracker`.
   The ZIP under `dist` contains this path and can be extracted into `/config`.
2. Restart Home Assistant.
3. Open Settings > Devices & services > Add integration > BurTracker.
4. Enter the exact tracker name from the event, initially
   `burtracker-hardware-test`. Separate multiple names with commas.
   Change the list later using the integration's Configure options.
5. In the ESPHome integration, configure the scanner and enable
   "Allow the device to perform Home Assistant actions".
6. Open HA's To-do lists page and select BurTracker Shopping.

No further firmware change is needed if the device is already sending the event.
BurTracker's list entity belongs to the BurTracker integration; it is not an entity
of the physical ESPHome device.

## Event contract implemented now

Event type: `esphome.burtracker_scan`

```yaml
schema_version: "1"
tracker: burtracker-hardware-test
barcode: "0012345678905"
intent: shopping
```

The integration accepts version 1 (string or integer) and the exact intent
`shopping`. It preserves leading zeros and rejects non-string/empty barcodes,
control characters, and values longer than 128 characters.
Other intents, versions, and unconfigured tracker names are ignored.

Tracker names are routing filters, not authentication. The HA event bus is trusted;
an HA user/automation able to fire events can supply these names. This prototype
does not claim cryptographic binding to an enrolled ESPHome device.

## Behavior

- First scan adds "Unresolved barcode: <barcode>".
- Further scans of that barcode leave the active item unchanged; they do not
  increase quantity, including when another household tracker scans it.
- Completing an item checks it off. A later scan reopens it and preserves its name.
- You can rename, create, complete, and delete items using HA's normal to-do UI.
- Renaming gives a useful household label; it does not establish a Krónan product ID.
- A completed item is not evidence of a purchase. This version has no purchase history.
- All scanned items remain unresolved against retailers. No prices or cart writes.
- No consumption/waste records, offline queue, or on-device acknowledgement yet.

After processing, HA emits `burtracker.scan_processed` with tracker, barcode,
outcome (`added`, `already_present`, `reopened`, or `save_failed`), and an item UID
on success. This is an HA-side diagnostic event, not a correlated reply to firmware.
It is intentionally separate from the inbound ESPHome event.

The current firmware has no request ID. Ensure-present semantics suppress active-list
duplicates, but cannot distinguish a delayed retry from an intentional rescan after
completion. Add boot/session + sequence IDs before introducing quantity increments,
durable scan history, or consumption/waste processing.

## Smoke test in HA

In Developer tools > Events, listen for `burtracker.scan_processed`. From another
browser tab fire `esphome.burtracker_scan` with the sample YAML above, then:

1. Confirm one unresolved entry appears.
2. Fire it again: outcome is already_present and list still has one active entry.
3. Rename it, complete it, and fire again: the same entry reopens with the saved name.
4. Restart HA: the list remains.
5. Scan physical packaging and verify the equivalent path.
6. Fire a consumed/spoiled or unknown-tracker event: shopping list remains unchanged.

## Local checks and limits

Run `python -m unittest discover -s tests -v`.
Portable tests cover event validation, leading zeros, shared-list duplicate handling,
completion/rescan, serialized data round trip, manual edits, and tracker options.
These do not replace running the integration in a real HA instance. This environment
does not have Home Assistant installed; setup UI, Store I/O, and entity lifecycle
still require the smoke test above.

Next slice: retailer lookup strategy, explicit match/unresolved/lookup-failed states,
then request IDs and a correlated display reply. Keep retailer cart export separate.

References:
- https://developers.home-assistant.io/docs/core/entity/todo/
- https://esphome.io/components/api/#homeassistantevent-action
