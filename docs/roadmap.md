# Delivery plan

All implementation milestones remain open. Order follows the dependencies that can invalidate later designs.

| Stage | Deliverable | Completion evidence |
| --- | --- | --- |
| 0. Foundation | Product brief, architecture proposal, preliminary BOM, Git | Documents committed locally; remote/visibility and license still open |
| 1. Feasibility | Scanner bench trial, Thread-to-host proof, Krónan read-only investigation | Real packaging results, power measurements, working routed/authenticated event, documented API coverage |
| 2. Shared list core | Event persistence, multi-device enrollment, unknown products, undo | Two device simulators; duplicate/reordered/replayed events; restart recovery; household isolation |
| 3. First vertical slice | One physical scan reaches shared list and HA; Krónan resolves product | Demonstrated scan, offline replay, HA reload, correct product mapping |
| 4. Retailer workflows | Purchase import and deliberate cart export where supported | Idempotent import, measured coverage, no duplicate writes after uncertain response, unrelated cart lines preserved |
| 5. Hardware revision A | Exact priced BOM, schematic, PCB, parametric enclosure | Power and scan measurements; ERC/DRC review; mechanical/RF fit; fabrication exports |
| 6. Household trial | Multiple installed trackers and usable mobile list | Record missed/accidental scans, duplicate entries, correction effort, availability, and user adoption |
| 7. Insights and release | Purchase trends, explicit waste reports, support/recovery documentation | Coverage labels, retention/deletion/export checks, firmware recovery, license and distribution decisions |

## Targets to agree before the trial

Set budget per device, prototype quantity, scan success rate and latency, offline queue duration/capacity, acceptable setup time, expected service uptime, enclosure dimensions, and battery runtime if applicable. Measure scanner energy first; MCU sleep-current figures alone do not predict complete-device battery life.

## Highest-priority unanswered questions

1. Is this primarily a personal HA project or a product for households without HA?
2. Is wired power acceptable at the intended installation locations?
3. Should repeat scans increment quantities or merely keep an item on the list?
4. How much explicit interaction is acceptable for marking spoilage?
5. What budget, dimensions, build quantity, and runtime should drive parts selection?
6. Which Krónan purchase channels and accounts must the first integration cover?

No implementation stage should be reported complete based solely on these design documents.
