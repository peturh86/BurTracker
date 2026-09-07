# Hardware design brief and preliminary BOM

Status: functional BOM only. No selected scanner, priced BOM, electrical schematic, PCB layout, fabrication files, or enclosure CAD yet. Quantities are per tracker unless marked otherwise. Do not order from this document without selecting and validating exact parts.

The target [ESP32-C6](https://www.espressif.com/en/products/socs/esp32-c6) supports IEEE 802.15.4 alongside Wi-Fi and Bluetooth LE. Prefer a module-based custom board for the first revision; exact module, flash capacity, antenna option, and stock need selection.

| Item | Qty | Candidate / requirement | Selection gate |
| --- | ---: | --- | --- |
| ESP32-C6 development board | 1 for bench only | Accessible UART and debug/programming interface | Confirm scanner wiring and power |
| ESP32-C6 module | 1 custom PCB only | Module with suitable antenna and flash | Pin budget, OTA/storage space, availability |
| Barcode scan engine | 1 | Decoded serial output, grocery barcode support, controllable trigger/sleep | Real-label tests, voltage, peak current, dimensions, optics |
| USB power input | 1 | USB-C power receptacle and appropriate sink configuration | Power budget and protection design |
| Power regulation/protection | 1 set | Rails sized for scanner and radio peaks; ESD and decoupling | Selected components and measured transient load |
| Scanner connector/interface | 1 set | Correct mating connector; level translation if needed | Engine electrical specification |
| User input | 1 provisional | Scan/wake button; reset/provisioning access | Gesture and wake testing |
| Visual feedback | 1 | Status LED with suitable drive circuitry | Visibility and power target |
| Audible feedback | 0–1 | Optional sounder and driver | Accessibility and mute preference |
| Debug/test access | 1 set | Programming and rail/signal test points | Fixture and recovery workflow |
| PCB/passives/fasteners | 1 set | Values and footprint choices TBD | Schematic and mechanical review |
| Enclosure/optical opening | 1 set | Cleanable housing with scanner field of view | Optical and assembly tests |
| Mounting system | 1 set | Retained magnets or alternative bracket/adhesive mount | Fridge compatibility, pull force, RF impact |
| Battery subsystem | optional | Cell, protection, charger/power path, sensing | Only after runtime and charging requirements agreed |
| Thread border router | shared | Compatible with deployment and provisioning method | End-to-end network proof |

For the released BOM, record manufacturer part number, supplier, quantity, unit price/currency/date, extended price, lifecycle, alternates, and datasheet. Include assembly, PCB fabrication, enclosure, cables, tax, and shipping in the prototype budget. No cost or runtime estimate has been validated.

## PCB gates

Select scanner before assigning UART pins, supply rails, connectors, or board outline. Measure idle, scan, radio, and wake currents. Build a pin table covering boot strapping, programming/debug, scanner trigger, feedback, and optional battery sensing. Follow the chosen module's antenna keepout and layout guidance. Evaluate metal fridge and magnet placement with the actual mounting geometry.

Create source schematic and PCB in a selected ECAD tool (KiCad proposed). Review electrical rules, power transients, antenna keepout, component clearances, enclosure interfaces, debug recovery, and assembly access. Run ERC/DRC with documented exceptions before producing Gerbers, drill files, placement data, and an exact BOM. Fabrication release follows bench validation and design review.

## Enclosure gates

Choose mounting location and orientation, target dimensions, power-cable route, materials, cleaning needs, assembly method, and scan distance. Keep the optical aperture clear through the entire field of view; validate any cover material for reflections and decode performance. Allow access to fasteners, USB, reset, and scanner servicing. Retain magnets mechanically and keep RF clearance measurable.

Produce parametric CAD plus STEP and prototype-print exports after component envelopes are known. Test mounting slip, repeated fridge-door impacts, drops, cable strain, cleaning, acoustic feedback, optical alignment, and wireless performance. Do not claim ingress protection, food-contact suitability, battery life, or product certification without validation.
