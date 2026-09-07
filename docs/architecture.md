# Architecture proposal

Status: proposed design, not implemented.

```text
Barcode engine -> ESP32-C6 -> Thread -> border router -> household service
                                                        |-> household list / mobile UI
                                                        |-> Home Assistant integration
                                                        |-> retailer strategy -> Krónan
```

Thread provides networking; it does not define barcode events, household authorization, or shopping-list semantics. Home Assistant documents the distinction between [Thread](https://www.home-assistant.io/integrations/thread/) and the [Matter application protocol](https://www.home-assistant.io/integrations/matter/). Matter must be evaluated separately for suitable barcode data and supported HA behavior; do not assume Thread makes this a native Matter device.

## Boundaries

- Firmware: scanner control, local feedback, stable device identity, durable event queue, authenticated transport, provisioning, updates.
- Household service: device enrollment, event acceptance, product mapping, list state, receipt import, retailer reconciliation, durable storage.
- HA integration: configuration, device health, scan events, shopping-list access, and service connection.
- Retailer strategy: provider-specific authentication, product identifiers, receipt/order semantics, and cart operations.

The service is logically independent of HA; packaging it with HA or separately remains open. Prototype an authenticated application transport over Thread before choosing the wire protocol. Validate discovery, IPv6 routing, sleepy-device behavior, provisioning, and recovery on the intended border router. Keep retailer tokens off the trackers.

## Domain records

| Record | Minimum information |
| --- | --- |
| Household | ID, members, active list, preferences |
| Device | ID, household binding, friendly name/location, credential identity, firmware version |
| Scan event | Schema version, globally unique event ID, device ID, sequence, raw barcode string, symbology, intent, optional device time |
| Accepted event | Event ID, household derived from authenticated device, server receipt time, processing state |
| Product mapping | Barcode identity, provider, provider product ID, pack size/unit, mapping provenance |
| List entry | Stable ID, product or unresolved barcode, requested quantity/unit, state, revision, contributing events |
| Purchase line | Provider account scope, receipt/order ID, line ID, purchase time, quantity/unit, amount/currency, status |
| Cart operation | Local operation ID, target account/cart, desired change, outcome, reconciliation state |
| Waste report | Product, optional quantity/unit, user-provided reason and time, provenance |

Barcodes are strings: preserve leading zeros and the original scanned value. Normalize only with validated symbology rules. Retailer SKU and barcode are separate identifiers. A product-level barcode is not an individual package identifier.

## Reliability rules

1. Persist each capture before claiming it is saved; report queue-full or storage failures visibly.
2. Retry with the same event ID after reboot or lost acknowledgements. Deduplicate by authenticated device and event ID within a database transaction that also updates list state.
3. Acknowledge only after durable acceptance. Do not require trustworthy device clocks for deduplication.
4. Separate transport retries from repeated physical scans. Separate physical scans remain events; proposed list policy ensures presence rather than incrementing implicitly.
5. Scope all data and device credentials to a household. Reject revoked or foreign devices.
6. Version list edits to detect concurrent changes. Undo is an explicit compensating action and must not remove another user's later request.
7. Import purchases idempotently using stable provider identities. Handle cancellations, refunds, pagination, and incremental-sync overlap.
8. Keep local capture operational during retailer outages. Back off on rate limits. After an ambiguous cart-write timeout, inspect provider state before retrying; local IDs alone cannot guarantee remote idempotency.

## Security and operations

Specify device enrollment and revocation, application-level authentication, encrypted secret storage, credential rotation, signed firmware updates with recovery, diagnostic redaction, retention settings, backups, and schema migration before household trials. Thread network membership alone does not authorize access to household data. Factory reset must remove device credentials. Exact queue capacity, retry limits, retention periods, and OTA mechanism remain to be measured and selected.
