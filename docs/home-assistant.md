# Home Assistant integration brief

Status: proposed; no custom component implemented.

Expose one household service connection and distinct devices for each tracker. Use stable device IDs so changing room names or network addresses does not create duplicate devices.

Proposed capabilities:

- Configuration flow for household-service discovery/connection and authentication; reauthentication and unload support.
- Per-device availability, last accepted scan, firmware version, queued-event count, and battery level only if measured.
- Scan events for automations, with event IDs so replay can be distinguished from new capture.
- Access to shared shopping-list state, unresolved products, and retailer-sync status.
- Explicit controls for undo, product resolution, and cart export as supported by the service.
- Diagnostics that omit tokens, raw receipt history, and unnecessary household identifiers.

Decide whether to expose a dedicated HA to-do list or bridge an existing HA shopping list after inspecting the relevant HA developer contracts. Avoid two independently authoritative lists. Confirm which quantities and metadata the chosen HA entity can represent; retain richer data in the household service if needed.

Validate two trackers in one home, reconnect after service restart, integration reload, revoked credentials, unavailable border router, event replay, and list edits from multiple clients. HA availability and internet availability must be distinguishable.

Networking references checked 2026-09-07: [HA Thread](https://www.home-assistant.io/integrations/thread/) and [HA Matter](https://www.home-assistant.io/integrations/matter/). Thread connectivity is not itself a custom-device integration. Application transport and provisioning remain an explicit feasibility milestone.
