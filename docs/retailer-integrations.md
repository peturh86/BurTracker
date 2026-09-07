# Retailer strategy and Krónan

Status: interface proposal and initial research, 2026-09-07. No authenticated API calls or external writes performed.

## Strategy contract

Keep provider payloads outside the core domain. Each adapter advertises capabilities independently: product lookup, barcode resolution, purchase history, purchase statistics, cart reading, and cart writing. Unsupported features must be explicit rather than returning misleading empty results.

Proposed operations: get capabilities; resolve barcode; search products; fetch purchase-history page with cursor; inspect cart; apply an explicit cart change; inspect an uncertain operation outcome when supported.

Normalize identifiers, quantities, units, currencies, timestamps, pagination, and error categories. Distinguish authentication expired, permission denied, rate limited, unavailable product, unsupported operation, conflict, transient failure, and unknown write outcome. Implement a fake adapter with synthetic data for development.

The adapter receives a household-scoped credential reference, never a firmware credential. Multiple retailer accounts in one home require a selected export target and deduplicated purchase import. Support reconnect and revocation without losing local lists.

## Evidence and remaining uncertainty

- Krónan has an official [REST API Swagger location](https://api.kronan.is/api/v1/schema/swagger-ui/). The search-rendered page reported failure loading its schema; this session did not obtain a usable official API contract there.
- Krónan's [receipt lookup page](https://kronan.is/leita-ad-kvittun) describes receipt access for signed-in users. That alone does not establish API history coverage.
- The implementation author of [kronan-mcp](https://github.com/sandsower/kronan-mcp) documents product lookup, checkout-line operations, orders, shopping notes, purchase statistics, and account access. Its README describes user-created access tokens and links a saved OpenAPI schema. This is useful implementation evidence, but not confirmation of current retailer guarantees.

The initial evidence makes the integration plausible. Still unverified: access available to this user's account; current official contract; barcode-to-SKU coverage; ordinary in-store purchase history versus online orders/statistics; historical depth; current scopes and rate limits; cart ownership; write idempotency; and supported third-party usage. Purchase statistics must not be treated as itemized receipts.

## First integration milestone

1. Obtain and review the current official API documentation and token creation flow. Store credentials locally outside Git; do not request tokens in project documents.
2. Validate account identity and product lookup with read-only calls. Record source date/version and sanitized response shapes.
3. Verify history against known purchases from ordinary tills, app-based purchases, refunds, and online orders. Document missing channels explicitly.
4. Compare scanned barcode, product ID, pack size, and cart quantity semantics using known products.
5. Implement the adapter with sanitized fixtures, capability checks, pagination, token-expiry handling, rate-limit backoff, and ambiguous-write handling.
6. Validate user-requested cart additions against a reviewed list, read the result back, and preserve unrelated cart contents. Checkout/payment remain out of scope.

If purchase history is unavailable, ship scan-to-list/product-resolution separately and label purchase insights unavailable. If a cart write times out without a provider idempotency mechanism, reconcile state before replay or surface an unresolved operation.
