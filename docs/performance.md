# Performance

Speed check of the API on the full generated dataset (Phase 10): 499,179 orders,
1.26 million order lines, 3.3 million stock movements, 1.37 million picking tasks,
489,248 shipments, 2,000 products and 11,520 bins.

## How it is measured

```bash
python scripts/benchmark_api.py --database database/warehouse_synthetic.db
```

The script logs in as the demo manager and calls the API behind every main page five
times (after one warm-up call), inside the API process, so the times are the server's own
work (database and Python), without network. Dashboards use the last 30 and 90 days *of
the data*. Limits: **500 ms** for a page, **1 second** for report-sized calls (90-day
reports, and the ML check of 60,000 forecast product-days). The script exits with an
error when a call is over its limit, so it can guard against regressions; with
`--report FILE` it also writes the table to a file.

Machine: 4-core Intel Xeon 2.1 GHz cloud VM, Python 3.12, SQLite.

## What was slow and what fixed it

| Page / call | Before | After | Cause and fix |
|---|---:|---:|---|
| Stock movement history (newest first) | 5,963 ms | 22 ms | sorted 3.3 million rows: index on `created_at` |
| Order list (newest first) | 529 ms | 21 ms | sorted 500,000 rows: index on `created_at` |
| Order search "SO-2026-0001" | 1,365 ms | 33 ms | joined every order to its customer: customers are found first; a search starting with "SO-" uses the order-number index |
| Order search by customer name | about 1,400 ms | about 100 ms | the same (matching customers first) |
| Shipment list | 459 ms | 33 ms | index on `shipped_at`, no join to orders unless needed |
| Supplier report | 537 ms | 282 ms | 1,067 queries (one per open purchase order): its lines are loaded in one query |
| Warehouse report | 846 ms | 232 ms | loaded a full product record for each of 19,000 stocked bins: each product's size is read once |
| Fulfillment report, 30 days | 748 ms | 405 ms | read every order timestamp into Python: per-day counts, on-time deliveries and durations are computed by the database |
| Fulfillment report, 90 days | 1,699 ms | 714 ms | the same |
| Inventory report, 90 days | 810 ms | 797 ms | stock at the start of the period read through the wrong index; now through `created_at` (the 90-day report still sums half a million movements) |
| ML accuracy check | 1,028 ms | 582 ms | timestamps converted one by one: orders are summed per product and day by the database |

The first measurement of the dashboards used "the last 30 days" from today, after the
dataset's last day, so they had less data; the "before" numbers for the reports above are
from re-measurements with the data's own last 30 / 90 days.

New indexes (migration `2d3500e1245f`): `inventory_movements (created_at, id)`,
`orders (created_at, id)`, `orders (shipped_at)`, `orders (delivered_at)`,
`shipments (shipped_at, id)`, `shipments (delivered_at)`, `picking_tasks (completed_at)`.

## Tried and rejected

- **SQLite statistics (`ANALYZE`)** helped one report but made the work queues slower:
  open picking tasks went from 10 ms to 1.1 s. The statistics only know the *average* rows
  per status, and the data is very lopsided (a handful of open tasks among 1.37 million
  finished ones), so SQLite stopped using the status indexes. The migration does not run
  `ANALYZE`; do not run it on this database.
- **Computing the fulfillment durations entirely in SQL** (count, average, median) was no
  faster than in Python (the database then does the same work), so the simpler code stayed.
- **The whole ML accuracy check as one SQL query** took about as long as the current code.

## Limits

- Searching orders by digits only (for example "000123") still reads all order numbers
  (about 0.5 s on the full dataset): digits can appear anywhere in a number.
- Reports over 90 days take 0.4 to 0.8 seconds: they go through hundreds of thousands of
  rows. Longer periods take proportionally longer.
- All times are on SQLite with one user. Many people working at once, or much more data,
  would call for PostgreSQL and caching of the reports.

## Results after the fixes

| Page | API call | Median | Slowest | Limit | |
|------|----------|-------:|--------:|------:|---|
| Dashboard | `GET /dashboards/overview?{days30}` | 270 ms | 395 ms | 500 ms | ✅ |
| Dashboard | `GET /alerts/summary` | 9 ms | 12 ms | 500 ms | ✅ |
| Dashboard | `GET /ml/summary` | 256 ms | 259 ms | 500 ms | ✅ |
| Reports | `GET /dashboards/inventory?limit=5&{days30}` | 415 ms | 544 ms | 500 ms | ✅ |
| Reports | `GET /dashboards/fulfillment?{days30}` | 405 ms | 444 ms | 500 ms | ✅ |
| Reports | `GET /dashboards/warehouse?{days30}` | 232 ms | 297 ms | 500 ms | ✅ |
| Reports | `GET /dashboards/suppliers?{days30}` | 282 ms | 414 ms | 500 ms | ✅ |
| Reports (90 days) | `GET /dashboards/inventory?limit=5&{days90}` | 797 ms | 881 ms | 1,000 ms | ✅ |
| Reports (90 days) | `GET /dashboards/fulfillment?{days90}` | 714 ms | 994 ms | 1,000 ms | ✅ |
| Reports (90 days) | `GET /dashboards/warehouse?{days90}` | 383 ms | 418 ms | 1,000 ms | ✅ |
| Products | `GET /products?limit=25` | 12 ms | 16 ms | 500 ms | ✅ |
| Products | `GET /products?q=lamp&limit=25` | 21 ms | 22 ms | 500 ms | ✅ |
| Product page | `GET /products/{product}` | 11 ms | 110 ms | 500 ms | ✅ |
| Product page | `GET /inventory/products/{product}` | 12 ms | 16 ms | 500 ms | ✅ |
| Product page | `GET /inventory/movements?product_id={product}&limit=25` | 12 ms | 16 ms | 500 ms | ✅ |
| Product page | `GET /ml/demand-forecasts/{product}` | 49 ms | 58 ms | 500 ms | ✅ |
| Product page | `GET /ml/movement-classification/{product}` | 11 ms | 13 ms | 500 ms | ✅ |
| Product page | `GET /ml/product-recommendations/{product}` | 21 ms | 25 ms | 500 ms | ✅ |
| Inventory | `GET /inventory?limit=25` | 68 ms | 70 ms | 500 ms | ✅ |
| Inventory | `GET /inventory?q=WH01-ZA&limit=25` | 71 ms | 104 ms | 500 ms | ✅ |
| Inventory | `GET /inventory/movements?limit=25` | 22 ms | 27 ms | 500 ms | ✅ |
| Inventory | `GET /inventory/approvals` | 10 ms | 18 ms | 500 ms | ✅ |
| Orders | `GET /orders?limit=25` | 21 ms | 25 ms | 500 ms | ✅ |
| Orders | `GET /orders?q=SO-2026-0001&limit=25` | 33 ms | 33 ms | 500 ms | ✅ |
| Orders | `GET /orders?status=backordered&limit=25` | 13 ms | 15 ms | 500 ms | ✅ |
| Order page | `GET /orders/{order}` | 14 ms | 16 ms | 500 ms | ✅ |
| Order page | `GET /orders/{order}/shipment` | 12 ms | 16 ms | 500 ms | ✅ |
| Order page | `GET /returns?order_id={order}&limit=50` | 11 ms | 14 ms | 500 ms | ✅ |
| Order page | `GET /ml/delay-risk/{order}` | 12 ms | 17 ms | 500 ms | ✅ |
| Fulfillment | `GET /picking-tasks?status=open&limit=50` | 11 ms | 17 ms | 500 ms | ✅ |
| Fulfillment | `GET /packing-tasks?status=open&limit=100` | 11 ms | 13 ms | 500 ms | ✅ |
| Shipments | `GET /shipments?limit=25` | 33 ms | 43 ms | 500 ms | ✅ |
| Shipments | `GET /shipments?status=delayed&limit=25` | 40 ms | 40 ms | 500 ms | ✅ |
| Purchase orders | `GET /purchase-orders?limit=25` | 31 ms | 39 ms | 500 ms | ✅ |
| Purchase orders | `GET /purchase-orders?overdue=true&limit=25` | 38 ms | 44 ms | 500 ms | ✅ |
| Suppliers | `GET /suppliers?limit=25` | 11 ms | 12 ms | 500 ms | ✅ |
| Warehouse layout | `GET /warehouses/{warehouse}/layout` | 65 ms | 151 ms | 500 ms | ✅ |
| Alerts | `GET /alerts?unresolved=true&limit=25` | 9 ms | 11 ms | 500 ms | ✅ |
| ML insights | `GET /ml/reorder-recommendations?status=pending&limit=25` | 24 ms | 31 ms | 500 ms | ✅ |
| ML insights | `GET /ml/slotting-recommendations?status=pending&limit=25` | 60 ms | 64 ms | 500 ms | ✅ |
| ML insights | `GET /ml/delay-risks?limit=25` | 24 ms | 24 ms | 500 ms | ✅ |
| ML insights | `GET /ml/movement-classifications/summary` | 40 ms | 135 ms | 500 ms | ✅ |
| ML insights | `GET /ml/models` | 155 ms | 178 ms | 500 ms | ✅ |
| ML insights | `GET /ml/accuracy` | 582 ms | 640 ms | 1,000 ms | ✅ |

44 calls, median of medians 28 ms, slowest 797 ms; 0 over their limit or failing.
