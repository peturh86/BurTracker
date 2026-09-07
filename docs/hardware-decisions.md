# Confirmed scope and revision A hardware selection

Updated 2026-09-07. This document supersedes earlier proposals for optional HA, battery power, and offline scan queues.

## Confirmed requirements

- Home Assistant is required; multiple trackers share the household list.
- ESP32-C6 with Thread preferred; Wi-Fi is acceptable.
- Exposed USB-C power input. External power supply and cable are outside scope. No battery subsystem.
- Dedicated barcode decoding for exact product identity; no vision-model product identification.
- Small SSD1306 display and three physical buttons.
- Default scan adds to shopping list. Explicit consumed/spoiled modes record those reports without automatically adding to the list.
- No offline scan storage/replay requirement. HA is assumed reachable. Unexpected disconnection must show an error rather than a saved indication.

## Selected prototype configuration

| Component | Quantity | Selection |
| --- | ---: | --- |
| MCU | 1 | ESP32-C6; exact module variant pending board layout |
| Display | 1 | SSD1306-based 128x64 I2C OLED, nominal 0.96 inch; exact module pending mechanical drawing |
| Controls | 3 | Shopping list, consumed, spoiled; switches/actuators pending enclosure |
| Barcode engine | 1 | DFRobot DFR0660 / GM65, using UART |
| Power input | 1 | Exposed USB-C receptacle with sink configuration and protection |
| Power/interface parts | 1 set | Regulation, decoupling, scanner connector and any required logic translation; values pending electrical review |
| Enclosure/mount | 1 set | Display opening, three button actuators, scan aperture, USB-C access, retained mounting hardware |

The [DFRobot GM65 product page](https://www.dfrobot.com/product-1996.html) lists UPC/EAN support, UART, integrated illumination, 5V supply, and 120mA scanning current. Listed scanner price is USD 49.90 on 2026-09-07, excluding shipping/taxes; this is not a complete device cost or stock guarantee. Selection is for the first prototype, subject to actual grocery-label tests. The engine decodes barcode symbols internally and sends the decoded value; HA maps it to a retailer product. There is no external vision model.

Verify scanner UART logic levels, connector pinout, mechanical drawing, trigger commands, and startup/peak current from the exact supplied revision before PCB release. Do not infer signal voltage from its 5V supply rating. Feed the scanner from the appropriate USB-derived rail and regulate the MCU/display supply. Include full load margin in USB input design.

## Proposed button behavior

Each button selects its labeled intent, visibly shown on the display. Consumed/spoiled selection is one-shot and returns to shopping-list mode after the scan finishes or an inactivity timeout. Exact timeout and scanner sensing/trigger behavior require a bench prototype. Show the product or raw barcode plus HA-confirmed result; decoder success alone is not list-update success. Treat ambiguous submission timeouts as unknown outcomes, not as safe-to-repeat failures.

Consumed/spoiled scans are user reports. They do not establish complete home inventory or exact discarded quantity. Preserve unknown barcode identity with its selected intent, and suppress repeated decoder output while packaging stays in front of the scanner.

## ESPHome candidate

[ESPHome OpenThread](https://esphome.io/components/openthread/) supports ESP32-C6 with ESP-IDF, HA communication, and a network dataset from HA. A Thread border router is required. Prototype onboarding, native API delivery of repeated identical barcode events, intent/event IDs, and return acknowledgements before committing firmware architecture. Wi-Fi is an alternative configuration, not a promise of automatic failover. Keep Krónan authentication in HA.

## Release gates

Test real EAN packaging, curved bottles, reflective/wet labels, scan distance, duplicates, mode reset, and HA-confirmed display feedback. Select exact OLED/switch parts and verify scanner dimensions before enclosure CAD and PCB outline. No hardware has been purchased, assembled, or tested yet.
