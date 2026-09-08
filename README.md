# BurTracker

## Install with HACS

Add https://github.com/peturh86/BurTracker as a HACS custom repository of type
**Integration**, download BurTracker, restart Home Assistant, then add BurTracker
under Settings > Devices & services. Works with Home Assistant Container when HACS
is installed in the persistent configuration volume.

See [setup instructions](docs/ha-integration-setup.md) for tracker enrollment and testing.

## Working prototype

The Core2 firmware is [m5stackcore2.yaml](m5stackcore2.yaml) plus [burtracker_ui.h](burtracker_ui.h), kept in the same folder. Its green/red/yellow tabs select Shopping, Spoiled, and Price.
Shopping scans now add matched products to the Krónan product list named **HA**.
The integration finds or creates that list at startup when a token is configured. See [installation and smoke test](docs/ha-integration-setup.md).
Krónan barcode lookup and product-name feedback are implemented in v0.2.0; configure an access token in HA and update the firmware. Active checkout and the dedicated analytics portal are not implemented.
Older architecture proposals below and in the charter are superseded where they
conflict with this implemented slice and the planned separate application/portal.


A household shopping-list manager with physical barcode trackers near the fridge or rubbish bin. Scanning packaging expresses replenishment intent; purchase history helps people understand buying habits. Multiple trackers contribute to one household.

BurTracker does not promise an accurate inventory. Missing scans, purchases elsewhere, shared products, and partial consumption make that impossible without extra work from users. Spoilage must be explicitly reported or clearly presented as an estimate.

## Project status

Discovery and design foundation, established 2026-09-07. No firmware, working integrations, PCB layout, or enclosure CAD exists yet. Hardware entries are a preliminary BOM, not a purchasing or manufacturing release.

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
