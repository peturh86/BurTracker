# BurTracker

## Install with HACS

Add https://github.com/peturh86/BurTracker as a HACS custom repository of type
**Integration**, download BurTracker, restart Home Assistant, then add BurTracker
under Settings > Devices & services. Works with Home Assistant Container when HACS
is installed in the persistent configuration volume.

See [setup instructions](docs/ha-integration-setup.md) for tracker enrollment and testing.

## Working prototype

The Core2 firmware is [m5stackcore2.yaml](m5stackcore2.yaml) plus [burtracker_ui.h](burtracker_ui.h), kept in the same folder. Its green/red/yellow tabs select Shopping, Spoiled, and Price.
Each accepted Shopping scan now adds one unit of a matched product to the Krónan product list named **HA**.
The integration finds or creates that list at startup when a token is configured. See [installation and smoke test](docs/ha-integration-setup.md).
Krónan barcode lookup and product-name feedback are implemented in v0.2.0; configure an access token in HA and update the firmware. Active checkout and the dedicated analytics portal are not implemented.
Older architecture proposals below and in the charter are superseded where they
conflict with this implemented slice and the planned separate application/portal.


A household shopping-list manager with physical barcode trackers near the fridge or rubbish bin. Scanning packaging expresses replenishment intent; purchase history helps people understand buying habits. Multiple trackers contribute to one household.

BurTracker does not promise an accurate inventory. Missing scans, purchases elsewhere, shared products, and partial consumption make that impossible without extra work from users. Spoilage must be explicitly reported or clearly presented as an estimate.

## Meal planner (0.6.4)

BurTracker stores recipes, dated meals, outcomes, feedback, pantry sightings, budgets, and verified Krónan product-price snapshots in HA's persistent `.storage` database. Home Assistant exposes the meal calendar and details, a separate tomorrow-meal sensor, feedback/status services, calendar-event access, and a loopback-only authenticated API. The private `meal-planner` Hermes profile connects through a 12-tool MCP server; it never writes SQLite directly.

The agent can search Krónan's official product and recipe APIs, re-read each selected SKU for current catalog price/pack/shortage data, total whole packages, and calculate the full basket and basket-per-planned-portion figure. LLM-generated/adapted recipes are saveable only after every ingredient is mapped to a Krónan SKU and the current product details pass checks. Krónan's linked-recipe product list is preview-only until the model audits recipe-text coverage. Obvious dairy products without Krónan's lactose-free tag are blocked for this household. Calendar events, budget targets, and feedback are provided to the model as evidence; pantry sightings are not treated as stock counts. Prices are catalog observations, not checkout guarantees; weighed products and in-store shelf availability can differ. Automatic shopping-list mutation is intentionally not enabled.

The store uses idempotent schema setup and a narrow feedback-metric migration; this is not a general migration framework. See [setup and API](docs/ha-integration-setup.md).

## Project status

Discovery and design foundation established 2026-09-07. Hardware remains a Core2 scanner prototype; no custom PCB/enclosure release yet.

## Documentation

- [Product scope and open decisions](docs/product.md)
- [System architecture and event semantics](docs/architecture.md)
- [Hardware BOM, PCB, and enclosure brief](hardware/README.md)
- [Home Assistant integration brief](docs/home-assistant.md)
- [Retailer strategy and Krónan investigation](docs/retailer-integrations.md)
- [Delivery milestones and acceptance criteria](docs/roadmap.md)

## Repository conventions

Use this repository for product documentation, firmware, service, integrations, electronics, and mechanical design. Add implementation directories when their work begins. Record proposed decisions separately from validated ones; update the relevant document when a decision changes.

Never commit retailer credentials, household purchase histories, device keys, or production databases. Use synthetic fixtures. Source CAD and schematics must be versioned alongside their release exports. Software and hardware licensing, remote repository owner, and visibility remain undecided.
