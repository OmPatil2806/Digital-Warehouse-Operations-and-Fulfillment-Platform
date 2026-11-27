# Digital Warehouse Operations and Fulfillment Platform

[![Backend CI](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/backend-ci.yml/badge.svg?branch=main)](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/backend-ci.yml)
[![Frontend CI](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/frontend-ci.yml/badge.svg?branch=main)](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/frontend-ci.yml)
[![ML CI](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/ml-ci.yml/badge.svg?branch=main)](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/ml-ci.yml)
[![Security](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/security.yml)
![Version](https://img.shields.io/badge/version-v0.9.0-blue)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/node-22.22%2B-339933?logo=nodedotjs&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

A full-stack platform that digitises the core operations of a modern distribution warehouse, from goods receipt to shipment, and adds a machine-learning decision-support layer built with **TensorFlow/Keras**.

The platform manages products, suppliers, physical storage locations, inventory, customer orders, picking, packing, shipping and returns, and shows the state of the warehouse through role-based dashboards. On top of the operational system, six ML use cases help forecast demand, prevent stockouts, place products intelligently, warn about delayed orders and recommend related products. Every model is compared against a simple baseline.

> **Status:** 🚧 Under active development, built step by step in 10 phases.
> **Phase 9 (ML application integration) is complete: `v0.9.0`.** See the [Roadmap](#roadmap).

---

## Documentation

| | |
|---|---|
| [User guide](docs/user-guide.md) | what each role does in the web app, step by step |
| [Architecture](docs/architecture.md) | the parts of the platform and how they work together |
| [API](docs/api.md) | login, roles, conventions and every endpoint ([OpenAPI](docs/openapi.json); interactive at `/docs` while the API runs) |
| [Database](docs/database.md) | design rules, a diagram per area, every table |
| [Machine learning](docs/ml.md) | the six use cases from data to dashboard |
| [Security](docs/security.md) · [Performance](docs/performance.md) | the security review and the speed check |
| [Demo scenario](docs/demo-scenario.md) | a 12–15 minute walkthrough through the four roles, with `python scripts/prepare_demo.py` to set it up |

---

## Problems Addressed

| # | Problem | How the platform solves it |
|---|---------|----------------------------|
| P1 | No location-level visibility of inventory | Bin-level stock with on-hand, reserved, damaged and available quantities |
| P2 | Manual, paper-based order processing | Digital order lifecycle with generated picking and packing tasks |
| P3 | Reactive replenishment | Demand forecasting and stockout-risk models with reorder recommendations |
| P4 | Random product placement | Movement classification and slotting optimisation |
| P5 | Delays detected only after they happen | Order-delay prediction with risk levels and contributing factors |
| P6 | No traceability of stock movements | Immutable inventory movements and audit logs |
| P7 | Data not used for decisions | Feature pipelines and trained models exposed through APIs and dashboards |
| P8 | No access control | JWT authentication and role-based permissions |

---

## Key Features

### Warehouse operations
- **Authentication & users**: JWT login, roles (Admin, Manager, Staff, Customer), activity logging
- **Product catalog & suppliers**: SKUs, categories, dimensions, lead times, purchase orders
- **Warehouse layout**: Warehouse → Zone → Rack → Shelf → Bin hierarchy with capacity and occupancy
- **Inventory management**: receipt, reservation, transfer, adjustment, returns, cycle counts, full movement history
- **Order fulfillment**: order lifecycle state machine, picking and packing tasks, shipments and tracking
- **Dashboards & alerts**: inventory, fulfillment, warehouse and supplier KPIs; low-stock and delay alerts
- **Audit**: who changed what, when, with old and new values

### Machine learning (TensorFlow/Keras)

| # | Use case | Baseline | Output |
|---|----------|----------|--------|
| 1 | Demand forecasting | Moving average / seasonal naive | 7/14/30-day demand per product |
| 2 | Reorder recommendation | Reorder-point formula | Stockout probability, reorder date and quantity |
| 3 | Movement classification | ABC analysis | Fast / Medium / Slow moving |
| 4 | Slotting optimisation | ABC-based slotting | Recommended bin and walking-distance reduction |
| 5 | Order-delay prediction | Logistic regression | Delay probability, risk level, contributing factors |
| 6 | Product recommendation | Frequently bought together | Top-K related products |

Trained and compared in Phase 8 ([ML Experimentation](#ml-experimentation)), used in the application since Phase 9 ([ML in the Application](#ml-in-the-application)).

---

## Tech Stack

| Layer | Technologies |
|-------|--------------|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, Axios, React Router, React Hook Form, Zod, Recharts |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, JWT |
| Database | SQLite |
| Machine learning | TensorFlow, Keras, TensorFlow Recommenders, Pandas, NumPy, scikit-learn |
| Testing & quality | Pytest, Vitest, React Testing Library, Ruff, Black, ESLint, Prettier |
| DevOps | Git, GitHub, GitHub Actions (CI/CD) |

---

## Authentication & Roles

### How login works

- **Access token**: a short-lived JWT (30 min) returned by `POST /auth/login`. The frontend keeps it **in memory only** and sends it as `Authorization: Bearer <token>`.
- **Refresh token**: a long-lived random token (7 days) set as an **httpOnly, SameSite=Lax cookie** that JavaScript cannot read. Only its SHA-256 hash is stored in the database.
- **Rotation**: every refresh replaces the refresh token. If an old, already-used refresh token is presented again (a sign of theft), **all sessions of that user are revoked**.
- The frontend refreshes automatically on a `401` (one shared refresh for parallel requests) and restores the session after a page reload.
- Passwords are hashed with **bcrypt** (via `pwdlib`). Policy: 8+ characters, max 72 bytes, at least one letter and one digit.
- Outside `development`/`test`, the API refuses to start with the default `SECRET_KEY`.
- **Failed logins**: 5 wrong passwords within 15 minutes lock the account for 15 minutes (HTTP 429; the login page says when to try again).
- Every API response carries security headers, CORS allows only the web app's origin, and unexpected errors return a plain message with a reference instead of technical details. The full security review is in [docs/security.md](docs/security.md).

### Auth endpoints (`/api/v1/auth`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/login` | Email + password → access token; sets the refresh cookie |
| `POST` | `/auth/refresh` | New access token from the refresh cookie (rotates the cookie) |
| `POST` | `/auth/logout` | Revokes the current session and clears the cookie |
| `GET` | `/auth/me` | The logged-in user |

### User management (`/api/v1/users`, admin only)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/users?q=&role=&is_active=&offset=0&limit=50` | Paginated user list; search name/email, filter by role and status |
| `POST` | `/users` | Create a user (default role: customer) |
| `GET` | `/users/{id}` | Get a user |
| `PATCH` | `/users/{id}` | Partial update (email, name, password, roles, active). A password change ends all the user's sessions |
| `POST` | `/users/{id}/deactivate` | Block login and end all sessions immediately |

Safety rules: an admin cannot deactivate themselves or remove their own admin role, and the last active admin can never be removed.

In the web app, administrators manage accounts on the **Users** page (create, edit roles, reset password, deactivate / reactivate).

### Roles

| Role | Responsibilities | Sees in the app |
|------|------------------|-----------------|
| **Admin** | Users, audit, everything else | Every page, plus Users and Audit log (admins pass every role check) |
| **Manager** | Master data, approvals, purchasing, KPIs, ML decisions | Dashboard, Products, Suppliers, Warehouse layout, Inventory, Purchase orders, Orders, Fulfillment, Shipments, Alerts, Reports, ML insights |
| **Staff** | Receiving, picking, packing, shipping, counting | The manager's pages except Suppliers; reads master data, stock losses wait for a manager |
| **Customer** | Placing and tracking their own orders | Dashboard, My orders, Shipments and returns (their own) |

Step by step for each role: [docs/user-guide.md](docs/user-guide.md).

The backend enforces roles with `require_roles(...)` on each endpoint; the frontend hides navigation and guards routes with `<ProtectedRoute roles={[...]}>`.

---

## Master Data & Warehouse Layout

### Catalog endpoints

| Area | Endpoints |
|------|-----------|
| Categories | `GET /categories` · `GET /categories/{id}` · `POST /categories` · `PATCH /categories/{id}` |
| Products | `GET /products?q=&category_id=&supplier_id=&is_active=&sort=&offset=&limit=` · `GET /products/{id}` · `POST /products` · `PATCH /products/{id}` · `GET /products/{id}/suppliers` |
| Suppliers | `GET /suppliers?q=&is_active=&sort=` · `GET /suppliers/{id}` · `POST /suppliers` · `PATCH /suppliers/{id}` |
| Supplier offers | `GET /suppliers/{id}/products` · `POST /suppliers/{id}/products` · `PATCH` / `DELETE /suppliers/{id}/products/{product_id}` |

- **Search** covers SKU, name, brand and barcode; the **category filter includes sub-categories**; sorting: `sku`, `name`, `unit_price`, `created_at` (prefix `-` for descending).
- **Exact decimals**: money and measurements are stored as integers of the smallest unit (cents, grams, millimetres) and returned as strings, e.g. `"899.99"`.
- **Nothing is deleted**: records are archived with `PATCH {"is_active": false}` and restored with `true`.
- SKUs and supplier codes are unique (stored in upper case); duplicates return `409`, missing or archived references `422`.
- A product has at most one **preferred supplier**.

### Warehouse layout endpoints

| Area | Endpoints |
|------|-----------|
| Warehouses | `GET /warehouses` · `POST /warehouses` · `GET` / `PATCH /warehouses/{id}` · `GET /warehouses/{id}/layout` (full tree with capacity totals) |
| Zones | `POST /warehouses/{id}/zones` · `PATCH /zones/{id}` · `POST /zones/{id}/generate` (bulk racks × shelves × bins) |
| Racks, shelves, bins | `POST /zones/{id}/racks` · `PATCH /racks/{id}` · `POST /racks/{id}/shelves` · `PATCH /shelves/{id}` · `POST /shelves/{id}/bins` · `PATCH /bins/{id}` |
| Bin lookup | `GET /bins?q=&warehouse_id=&zone_id=` · `GET /bins/by-code/{code}` (scan) · `GET /bins/{id}/fit?product_id=&quantity=` (capacity check) |

### Location codes

Every bin has a unique location code built from its parents:

```
WH01 - ZA - R05 - S03 - B08
 |     |    |     |     +-- bin    (B + 2–3 digits)
 |     |    |     +-------- shelf  (S + 2 digits; level 1 = floor)
 |     |    +-------------- rack   (R + 2–3 digits; has a distance to the packing station)
 |     +------------------- zone   (Z + 1–2 letters; picking, bulk, cold, hazardous or returns)
 +------------------------- warehouse (WH + 2–4 digits)
```

- Codes are fixed after creation (they are printed on labels).
- **Bulk generation** creates up to 5,000 bins in one all-or-nothing transaction.
- Archiving a zone or rack also archives everything below it; restoring works one level at a time.
- Bins have a maximum weight and volume; `GET /bins/{id}/fit` checks whether more units fit on top of what the bin already holds.

### Permissions

| Data | Read | Change |
|------|------|--------|
| Categories, products | every logged-in user (customers: active only, without costs) | admin, manager |
| Suppliers and their offers | admin, manager, staff | admin, manager |
| Warehouse layout | admin, manager, staff | admin, manager |
| Users | admin | admin |
| Stock, movements, requests, cycle counts | admin, manager, staff | see [Inventory Operations](#inventory-operations) |
| Alerts | admin, manager, staff | admin, manager |
| Audit log | admin | nobody (append-only) |
| Orders, shipments, returns | warehouse roles; customers: their own | see [Orders & Fulfillment](#orders--fulfillment) |

### Demo data

```bash
# from the project root, after `alembic upgrade head`
python scripts/seed_database.py           # add demo data (safe to run again)
python scripts/seed_database.py --reset   # delete demo data and load it again (asks first)
```

Creates 4 demo users, 8 categories, 10 suppliers, 50 products (with valid EAN-13 barcodes), 60 supplier offers, warehouse **WH01** with 4 zones and 274 bins, **initial stock** for 49 products (one product per bin; chilled goods in cold storage, heavy goods in bulk), 6 low-stock alerts, one damage report waiting for approval, 4 carriers, 3 customers (Chris Customer is the `customer@example.com` login), 7 orders at different stages (created, backordered, reserved, picking, in transit, delayed, delivered and returned) and 3 supplier purchase orders (one overdue with an alert, one on its way that fills the backorder when received, one draft). Demo logins (development only):

| Email | Role | Password |
|-------|------|----------|
| `admin@example.com` | Admin | `Demo-pass-123` |
| `manager@example.com` | Manager | `Demo-pass-123` |
| `staff@example.com` | Staff | `Demo-pass-123` |
| `customer@example.com` | Customer | `Demo-pass-123` |

`--reset` only works when `APP_ENV` is `development` or `test`, and keeps users that are not demo users.

---

## Inventory Operations

Stock is tracked **per product and bin**:

```
available = on hand − reserved − damaged
```

Every change writes one **immutable movement** (the database refuses UPDATE and DELETE on `inventory_movements`) and one **audit record**, in the same transaction as the change. Stock can never go negative: the services and database CHECK constraints both enforce it, and concurrent changes to the same stock are refused with a 409 ("please retry") instead of being lost (optimistic locking).

| Operation | Effect | Who |
|-----------|--------|-----|
| Receive | on hand + (bin capacity is checked, including what is already stored) | admin, manager, staff |
| Transfer | out of one bin, into another; only available units move; total unchanged | admin, manager, staff (*) |
| Adjust: increase / decrease | units found / missing | admin, manager, staff (*) |
| Adjust: damage / restore / write off | mark damaged, sellable again, remove damaged units | admin, manager, staff (*) |
| Reserve / release | hold available units (orders reserve automatically); picking zones and racks near packing first | admin, manager |
| Cycle count | count a bin; a second person approves the differences | staff count, managers approve |

(*) **Manager approval ("four-eyes")**: staff adjustments that lose stock (decrease, damage, write-off) and staff transfers to another warehouse become **requests**. A request is checked when it is created and again, against the stock at that moment, when a manager approves it. Nobody can approve their own request or count.

**Alerts** are raised and resolved automatically after every stock change: *low stock* (available below the product's `min_stock`; critical at zero) and *bin over capacity*. There is at most one unresolved alert per cause; managers acknowledge or resolve them.

### Inventory endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/inventory?q=&warehouse_id=&zone_id=&bin_id=&product_id=` | Stock per product and bin |
| `GET` | `/inventory/products/{id}` | One product: totals and the bins that hold it |
| `GET` | `/inventory/movements?product_id=&bin_id=&movement_type=&since=&until=` | Movement history, newest first |
| `POST` | `/inventory/receive` | Receive goods into a bin |
| `POST` / `GET` | `/inventory/adjustments` | Adjust stock (`applied: false` = request); list adjustments |
| `POST` / `GET` | `/inventory/transfers` | Move stock; list transfers |
| `POST` | `/inventory/{adjustments\|transfers}/{id}/approve` · `/reject` · `/cancel` | Decide or withdraw a request |
| `GET` | `/inventory/approvals` | Requests waiting for a manager |
| `POST` / `GET` | `/inventory/reservations` · `/{id}/release` | Reserve, list and release stock |
| `GET` / `POST` | `/cycle-counts` · `/{id}` · `/{id}/lines` · `/submit` · `/approve` · `/reject` · `/cancel` | Cycle counts |
| `GET` | `/alerts?unresolved=&status=&alert_type=` · `/alerts/summary` | Alerts and the unresolved count |
| `POST` | `/alerts/{id}/acknowledge` · `/resolve` | Handle an alert (managers) |
| `GET` | `/audit-logs?entity_type=&entity_id=&actor_id=&action=` | Audit log (admins) |

### In the web app

- **Inventory**: stock per bin, "where is this product?", movement history, Receive / Move / Adjust forms with live capacity checks, **Approvals** (managers) or **My requests** (staff), and **Cycle counts**.
- **Alerts**: everything that needs attention, with a counter in the sidebar.
- **Audit log** (admins): who changed what and when, with old and new values.

---

## Orders & Fulfillment

Every order follows one state machine (project document, section 9.2). Invalid changes, such as cancelling a shipped order, are refused, and every change is written to the order's history (from, to, who, why).

```
created → confirmed → inventory_reserved → allocated → picking → picked
        → packing → packed → shipped → delivered → (returned)

exceptions: partially_allocated / backordered (not enough stock yet),
            on_hold (back to where it was), cancelled (before picking), delayed
```

| Stage | What happens |
|-------|--------------|
| **Place** | Prices are copied from the catalog; the shipping address from the customer; order numbers `SO-<year>-<sequence>` |
| **Confirm** | Stock is reserved at once from one warehouse, best bins first. Missing units make the order *partially allocated* or *backordered*; they are reserved automatically when stock arrives (urgent orders first) |
| **Allocate** | One picking task per reservation, along one route: farthest from packing first, then shelf and bin |
| **Pick** | The picker scans the bin and the product (SKU or barcode); a `pick` movement lowers on-hand and reserved. A **short pick** writes off the missing units, opens a cycle count for the bin and reserves a replacement from another bin if possible |
| **Pack** | The packer counts every line into the parcels (must equal what was picked) and records parcels and weight |
| **Ship** | Carrier, tracking number (given or generated) and expected delivery date (carrier transit time in working days) |
| **Track** | Events: in transit, out for delivery, delayed (raises a `delay_risk` alert), delivered (resolves it), exception. Overdue shipments can be marked delayed in one go |
| **Return** | Customers open returns for delivered units (never more than shipped). Staff inspect them: *restock* or *damaged*, into a returns-zone bin, with a `return` movement |

### Who can do what

| Action | Who |
|--------|-----|
| See orders, shipments, returns | warehouse roles: all; customers: only their own (other records answer 404) |
| Place, confirm, cancel an order | managers (for any customer); customers (for their own account) |
| Hold, release, retry a reservation, check delays | managers |
| Allocate, pick, pack, ship, add tracking events, inspect returns | admin, manager, staff |

### Order endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` / `POST` | `/customers`, `/customers/{id}`, `/customers/me` | Customers (managers create and change them) |
| `GET` / `POST` | `/orders`, `/orders/{id}` | List (scoped) and place orders |
| `POST` | `/orders/{id}/confirm` · `/cancel` · `/hold` · `/release` · `/reserve` · `/allocate` | Status changes |
| `GET` / `POST` | `/picking-tasks` · `/{id}/start` · `/{id}/complete` | Picking work queue and scan confirmation |
| `GET` / `POST` | `/packing-tasks` · `/{id}/start` · `/{id}/complete` | Packing work queue |
| `GET` | `/carriers` | Active carriers |
| `GET` / `POST` | `/shipments`, `/shipments/{id}`, `/shipments/{id}/events`, `/shipments/check-delays` | Shipping and tracking |
| `GET` / `POST` | `/returns`, `/returns/{id}/inspect` · `/cancel` | Returns |

### In the web app

- **Orders**: customers see *My orders* and place their own; managers order for any customer and see the available stock per line. The order page shows the lines, shipment tracking, returns, the full timeline and the next possible actions.
- **Fulfillment** (warehouse roles): the picking queue with scan confirmation and short picks, and packing with counting, followed straight by shipping.
- **Shipments**: tracking and updates, *Check delays* (managers), and the **Returns** tab with inspection.

### Supplier purchase orders

New stock is ordered from suppliers with purchase orders (`PO-<year>-<sequence>`):

```
draft → ordered → partially_received → received
  (draft or ordered, nothing received yet) → cancelled
```

- **Draft** (managers): one supplier, one warehouse, several products. The unit cost comes from the supplier's offer (else the product's purchase cost) and the expected date from the longest lead time, unless entered. The supplier's minimum order quantity is checked.
- **Receive** (warehouse roles): line by line into bins of the PO's warehouse, also in several deliveries; never more than ordered, and the bin's weight and volume are checked. Each receipt is a normal `receipt` movement naming the PO, so waiting backorders are filled and low-stock alerts resolve at once.
- **Overdue**: *Check overdue* raises an `overdue_supplier` alert for every PO still waiting after its expected date (critical after a week). Full receipt or cancellation resolves it.

| Method | Path | Who |
|--------|------|-----|
| `GET` | `/purchase-orders` (`status`, `supplier_id`, `q`, `overdue`), `/purchase-orders/{id}` | admin, manager, staff |
| `POST` | `/purchase-orders`, `/{id}/order`, `/{id}/cancel`, `/check-overdue` | admin, manager |
| `POST` | `/purchase-orders/{id}/receive` | admin, manager, staff |

In the web app: **Purchase orders** (Warehouse section): list with filters and overdue marks, a form for new orders, and the receiving form with bin lookup.

---

## Dashboards & Reporting

KPIs from section 9.4 of the project document, computed from the operational tables so they always agree with the rest of the application. *Stock* KPIs describe the warehouse now; *period* KPIs count events in a chosen date range (UTC days, both ends included, default the last 30 days, at most 366 days).

| Area | KPIs |
|------|------|
| **Inventory** | stock value at cost and selling price, available / reserved / damaged units, low-stock and out-of-stock products, inventory turnover (cost of units picked ÷ average stock value), days of supply, value per category, per-product demand |
| **Fulfillment** | orders placed, shipped, delivered and cancelled per day, fulfillment time (confirmed → shipped) and order cycle time (placed → delivered) as average and median, on-time delivery rate, picking accuracy, orders by status |
| **Warehouse** | bin occupancy, weight and volume use per zone and in total, picks per zone |
| **Suppliers** | lead time (ordered → fully received) average, variance and standard deviation, on-time delivery rate, open and overdue purchase orders |

Earlier stock levels are rebuilt from the immutable movement history; demand means units *picked* for orders (receipts, transfers and corrections are not demand). Every KPI is tested on hand-built data whose answers are known in advance.

### Dashboard endpoints (`/api/v1/dashboards`)

| Method | Path | Who | Money values |
|--------|------|-----|--------------|
| `GET` | `/overview` | admin, manager, staff | admin, manager |
| `GET` | `/inventory` (`limit`) | admin, manager, staff | admin, manager |
| `GET` | `/fulfillment` | admin, manager, staff | none |
| `GET` | `/warehouse` | admin, manager, staff | none |
| `GET` | `/suppliers` | admin, manager, staff | admin, manager |

All take `date_from` and `date_to` (ISO dates). Customers receive 403.

### In the web app

- **Home page by role**: managers see KPI tiles, orders per day, stock status, the products running out first and the latest alerts for a chosen period; staff see today's work (to pick, to pack, shipped, delayed, low stock, purchase orders to receive); customers see their own orders and parcels.
- **Reports** (managers and staff): Inventory, Fulfillment, Warehouse and Suppliers tabs with KPI tiles, charts and tables; the tab and period stay in the address bar.
- **Every chart has a table view** with the exact numbers. Charts use a colour-blind-safe palette (validated), status shown with icons and words, never colour alone.
- **Export CSV** on every report tab: raw values (plain numbers, ISO dates, UTF-8) for Excel or pandas; staff exports leave out money; cells that look like spreadsheet formulas are neutralised. (Excel with German regional settings: open via *Data → From Text/CSV* and choose comma as separator.)
- The ML insight KPIs (forecast error, predicted stockouts, high-risk orders) follow in Phases 8 and 9.

---

## Synthetic Data

Real warehouse data is not available, so a generator creates a large, relationally consistent **two-year history** (section 11 of the project document). It is not random rows: a day-by-day simulation runs the warehouse with the same rules as the application (reservations, picking, capacity limits, status transitions), and business patterns are built in on purpose so the ML models in Phase 8 have something real to learn, plus controlled noise.

### Generate it

From the project root, with the virtual environment active and `ml/requirements.txt` installed:

```bash
python scripts/generate_data.py                          # small: 500 orders, a few seconds
python scripts/generate_data.py --size medium            # 50,000 orders, about 1-2 minutes
python scripts/generate_data.py --size full --replace    # 500,000 orders, about 20 minutes
```

| Option | Meaning |
|--------|---------|
| `--size` | `small` (development and CI), `medium`, `full` (analytics and ML training) |
| `--seed` | random seed (default `20261111`): the same size, seed and end date always give the same data |
| `--end-date` | last day of the history, `YYYY-MM-DD` (default: today) |
| `--database` | the SQLite file (default `database/warehouse_synthetic.db`, not committed) |
| `--replace` | delete an existing file first (otherwise it is never overwritten) |
| `--no-demo-users` | do not add the demo logins (they are only added in development anyway) |

The command prints one progress line per simulated month and runs five stages: master data and warehouse layout → two years day by day → the application's alerts on the last day (low stock, bins over capacity, delayed shipments, overdue purchase orders) → demo logins → validation. It ends with exit code 1 if any validation check fails.

To explore the data in the web app, point the backend at it in `.env` and log in with a demo account (e.g. `manager@example.com` / `Demo-pass-123`):

```
DATABASE_URL=sqlite:///./database/warehouse_synthetic.db
```

### Sizes

| | small | medium | full |
|---|---:|---:|---:|
| Warehouses / zones / racks / bins | 1 / 4 / 20 / 300 | 1 / 6 / 60 / 1,440 | 3 / 18 / 180 / 5,760 |
| Products / suppliers / customers | 50 / 10 / 200 | 500 / 30 / 2,000 | 2,000 / 100 / 10,000 |
| Orders (two years) | ~500 | ~50,000 | ~500,000 |
| Generation time (measured) | 3 s | 72 s | 18 min |

The full dataset has 499,179 orders with 1.26 million order lines, 1.37 million picking tasks, 489,248 shipments with 2.0 million tracking events, 42,045 returns, 67,923 purchase orders and 3.3 million inventory movements (about 2.6 GB). Daily demand per product (2,000 products × 730 days) is derived from the order lines in Phase 8.

### How it is generated

Generation follows the order of the project document, in `ml/data_generation/` (`pipeline.py` runs everything):

1. **Master data** (`generate_master_data.py`): categories, products with demand profiles, suppliers with their true reliability, customers, carriers.
2. **Warehouse layout** (`generate_warehouse_layout.py`): warehouses > zones > racks > shelves > bins with weight and volume limits.
3. **Two years, one day at a time** (`simulation.py`), each day in a fixed order:
   - **Purchasing** (`generate_purchasing.py`): opening stock; a simple reorder-point policy that ignores seasons and promotions on purpose (room for the ML reorder model); deliveries after the supplier's real lead time, waiting at the dock when bins are full.
   - **Shipping and returns** (`generate_shipments.py`): carriers, tracking events, delays, deliveries, returns inspected and put back into stock.
   - **Orders** (`generate_orders.py`): daily order count from the demand patterns, stock reserved like the application does, backorders retried after deliveries.
   - **Fulfillment** (`generate_fulfillment.py`): picking routes, short picks with write-offs and cycle counts, packing into parcels, a daily cut-off and picking capacity.
   - **Housekeeping**: weekly disposal of damaged goods and returns moved back to storage.
4. **Alerts** as the application would show them on the last day.

Rows are written in batches while the simulation runs, so memory stays manageable on a local PC.

### Built-in patterns (measured on the full dataset)

| Area | Pattern | Full dataset |
|------|---------|-------------:|
| Demand | weekdays busier than weekends | 1.90× orders per day |
| | November-December holiday peak | 1.28× |
| | growth: second year above the first | 1.09× |
| | fast movers: the top 20 % of products | 59 % of units |
| | intermittent ("lumpy") demand | 11 % of regularly sold products sell in bursts |
| | promotions | 1-3 per product and year (not for lumpy products), 1.5-3× demand |
| Baskets | products bought together (e.g. laptop with mouse, bag, dock) | 572 product pairs with lift > 3 |
| Suppliers | different lead times | 2.3 to 30.8 days on average |
| | less reliable in peak season | 39 % late vs 25 % |
| Delays | late deliveries overall | 9.3 % |
| | large orders (> 10 units) | 17.6 % vs 8.9 % late |
| | orders that waited for stock | 30.3 % vs 8.4 % late |
| | December | 17.6 % vs 8.0 % late |
| | carriers differ in reliability | 7.4 % to 13.8 % late |
| Warehouse | heavy goods (≥ 8 kg) on the lowest shelf | 58 % vs 24 % of light goods |
| | fast movers stored nearer to packing | 26 m vs 47 m picking distance |
| | bin capacity limits never exceeded | 0 bins over their limits |
| Noise | returns | 2.6 % of shipped units, 36 % of returned lines damaged |
| | short picks and stock corrections | 0.41 % of picking tasks, 22,988 adjustments |

### Validation

`ml/data_validation/validate_dataset.py` checks a generated database and writes a Markdown report (the generate command runs it automatically; it can also run alone: `cd ml` then `python -m data_validation.validate_dataset --size full`):

- **Integrity**: no orphan records, no negative stock, stock equal to the sum of its movement history, bins within their limits, reservations matching reserved stock, movements pointing to existing documents, order lines, statuses, shipments, cancellations, returns, purchase orders and picking tasks consistent.
- **Volume**: the counts of the size configuration (warehouses, bins, products, customers, orders ± 10 %, two years of history).
- **Patterns**: the 19 patterns above (skipped below 10,000 orders, where they cannot be measured reliably).

The full dataset passes all 49 checks: see the [validation report](ml/data_validation/reports/full_dataset.md). CI generates and validates the small dataset on every push.

---

## ML Experimentation

Six use cases (section 12 of the project document) are trained offline on the synthetic dataset. Each compares simple **baselines** with several **TensorFlow/Keras** models on the most recent 90 days (the test period), which no model saw while training. A network is selected only if it beats the best baseline; otherwise the baseline is kept. Every model, baselines included, is recorded in the **model registry** (`model_versions`, `model_metrics`) with its dataset, features, hyperparameters and metrics; the selected models make the predictions the application shows ([ML in the Application](#ml-in-the-application)).

### Train the models

From the project root, after generating the dataset (`python scripts/generate_data.py --size full`):

```bash
python scripts/train_models.py                                   # all six use cases
python scripts/train_models.py --use-case demand_forecasting reorder
python scripts/train_models.py --quick                           # 1 epoch each: checks the pipeline
```

Each use case writes its comparison to `ml/evaluation/reports/<use case>.md`; the command ends with the [overview of all use cases](ml/evaluation/reports/overview.md). Settings (split, epochs, hyperparameters) are in `ml/configs/*.yaml`. Trained models are saved under `ml/artifacts/` (not committed). On the full dataset the whole run took about an hour on a 4-core CPU (no GPU): demand 16 min, reorder 8, movement 2, slotting 2, delay 5, recommendation 24.

### How the models are compared

- **Chronological split**: train 580 days, validation 60 days (early stopping, decision thresholds), test the last 90 days. Features only use what was known at the time (no future leakage), and every model answers exactly the same questions as its baselines.
- **Reproducible**: fixed seeds; the same dataset and settings train the same models.
- **Business rules first**: slotting never breaks a zone, weight or volume rule; movement groups only count if they are stable and useful.

### Results on the full dataset

| Use case | Baseline(s) | Networks compared | Selected | Test result |
|----------|-------------|-------------------|----------|-------------|
| Demand forecasting | moving average, seasonal naive | LSTM, GRU, CNN-LSTM, Transformer | **LSTM** | error of the 7/14/30-day totals 35.1 % vs 41.2 % for the moving average (−15 %); 86 % of days inside the 80 % forecast range |
| Reorder recommendation | reorder-point formula | Dense, Wide & Deep, LSTM | **LSTM** | stockout PR-AUC 0.328 vs 0.166; catches 52 % of stockouts while flagging 20 % of products (formula: 49 % / 31 %); with priority, reorder date, quantity and reasons |
| Movement classification | ABC analysis | Autoencoder + K-Means, VAE + K-Means, Deep Embedded Clustering | **ABC** (baseline) | no learned grouping was both stable across seeds and useful (fast class carrying most picks); ABC's fast class carries 79 % of next-period picks |
| Slotting | ABC slotting | Dense and Wide & Deep suitability networks + constrained optimizer | **Dense suitability** | 49.8 % less estimated picking time than the current layout (ABC 49.7 %, perfect foresight 50.1 %), 0 rule violations |
| Order-delay prediction | logistic regression | Dense, Wide & Deep, Deep & Cross, LSTM on order events | **LSTM on events** | PR-AUC 0.119 vs 0.116, well calibrated; the simulator's own delay formula reaches only 0.114 on this period, so delays are mostly chance here |
| Product recommendation | frequently bought together | NCF, Two-Tower, Deep & Cross, GRU | **Frequently bought together** (baseline) | held-out product in the top 10 for 56 % of baskets (best network: Two-Tower, 46 %) |

**What the results say**: the networks win clearly where the data has learnable structure that the simple rules ignore (seasonal demand, stockouts before peaks). Where the simple rule already matches how the data arises (baskets built from product pairs, groups defined by pick rate) or the outcome is mostly chance (delays), the baseline is as good or better, and the selection keeps it. Two notes: TensorFlow Recommenders needs the older Keras 2, so the Two-Tower model is written in plain Keras 3; the slotting pick time is an estimate (walking, handling, heavy goods up high), and the cost of moving stock into a new layout is not counted.

---

## ML in the Application

The selected model of every use case makes predictions **offline**, in one scoring command; the application only reads them. TensorFlow is therefore not needed by the backend, and pages stay fast.

```
selected model (registry) -> scripts/score_models.py -> prediction tables -> /api/v1/ml -> web app
```

### Score the models

From the project root, after training (`python scripts/train_models.py`):

```bash
python scripts/score_models.py                         # all six use cases, as of the last day of data
python scripts/score_models.py --use-case reorder      # only some use cases
python scripts/score_models.py --backtest 30           # check: forecasts and delays as of 30 days earlier
python scripts/check_models.py                         # models load; predictions complete and valid
```

`check_models.py` checks that every selected network loads from its saved file and gives finite outputs of the right shape. It also checks that the stored predictions cover what they should (every product, all 30 forecast days, every parcel on its way, ranks without gaps) with finite, consistent values. ML CI runs it after scoring and fails if a check fails.

**Training on GitHub**: the *Train models* workflow (Actions tab → *Train models* → *Run workflow*) generates a dataset of the chosen size (small, medium or full), trains and compares all six use cases, scores, checks and backtests. The comparison reports and the trained `.keras` models can then be downloaded from the run's page for 30 days.

Every run adds rows (`scored_at`, `as_of`) and keeps the earlier ones. The application shows the run with the latest `as_of`, so a backtest never replaces the current predictions. On the full dataset scoring takes a few minutes on a CPU, and the backtest about a minute.

### Where the predictions appear

| Where | What | Who |
|-------|------|-----|
| Dashboard | Predicted stockouts, high-risk deliveries, demand of the next 7/30 days with the latest forecast error, slotting moves | Manager |
| ML insights → Reorder | Products likely to run out within 14 days: risk, order-by date, quantity, reasons; **approving drafts a purchase order** for the default (or preferred) supplier, at least its minimum quantity | Manager decides, staff reads |
| ML insights → Slotting | Better bins, biggest picking-time saving first (zone, weight and volume rules kept); approve or reject | Manager decides, staff reads |
| ML insights → Delay risk | Shipments on their way, most likely to be late first, with reasons | Manager, staff |
| ML insights → Movement | Fast, medium and slow movers and their share of picks | Manager, staff |
| ML insights → Models | The model in use per use case and its test result; **predictions vs reality** | Manager, staff |
| Product page | 30-day demand forecast with its likely range, movement class, frequently bought together | Warehouse roles (related products for everyone) |
| Order page | Delivery risk while the parcel is on its way | Warehouse roles |

Every approve and reject is recorded in the audit log. A product without a supplier cannot be approved for reordering: nothing is saved and the reason is shown.

### ML endpoints (`/api/v1/ml`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/models`, `/summary`, `/accuracy` | Models in use; dashboard numbers; predictions vs reality |
| GET | `/demand-forecasts/{product_id}` | 30 days of forecast with range, and 7/14/30-day totals |
| GET | `/reorder-recommendations` | Filter by decision, priority, warehouse |
| POST | `/reorder-recommendations/{id}/approve` · `/reject` | Decide (manager, admin); approval drafts a purchase order |
| GET | `/movement-classifications`, `/movement-classifications/summary`, `/movement-classification/{product_id}` | Movement classes |
| GET | `/slotting-recommendations` · POST `/{id}/approve` · `/reject` | Slotting moves and decisions |
| GET | `/delay-risks`, `/delay-risk/{order_id}` | Delivery risk of shipments on their way |
| GET | `/product-recommendations/{product_id}` | Top 10 related products (customers: active products only) |

### Predictions vs reality

Predictions made before the last day with orders are compared with what happened next. With `--backtest 30` on the full dataset (made on 11 October, checked on the 30 days after, which the models never saw):

| Check | Result |
|-------|--------|
| Forecast error of each product's 30-day total | **26 %** (25 % in testing: the model holds up) |
| All products together | 4.2 % too low (94,930 units forecast, 99,117 ordered) |
| Days inside the likely range | 86 % of product-days (the range aims at 80 %) |
| Late deliveries by predicted risk | high 1 of 1, medium 24 %, low 16 %; 35 % of late parcels had been marked medium or high |

The forecasts are reliable for planning totals; single product-days remain hard to predict. The delay model ranks risk in the right direction but is weak, as expected from Phase 8 (delays are mostly chance in this data), so the dashboard counts only high-risk deliveries.

---

## Architecture

```
            React Frontend (TypeScript + Tailwind)
                          |
                    REST / JSON
                          v
                   FastAPI Backend
     Routers -> Services -> Repositories -> SQLAlchemy
               |                          |
               v                          v
        SQLite Database           Offline ML Scoring
   operational, feature and    selected .keras models
     prediction tables         -> prediction tables
               ^                          ^
               +------------+-------------+
                            |
                Offline ML Training Pipeline
   data generation -> features -> training -> evaluation -> registry
                            |
                    GitHub Actions CI/CD
        tests | lint | build | ML checks | release packaging
```

---

## Roadmap

The project is delivered in **10 phases**. Each phase ends with passing CI and a tagged release.

- [x] **Phase 1: Project foundation**: running skeleton of frontend, backend, database and CI (`v0.1.0`) ✅
- [x] **Phase 2: Authentication & authorization**: secure login and role-based access (`v0.2.0`) ✅
- [x] **Phase 3: Master data & warehouse layout**: products, suppliers and physical locations (`v0.3.0`) ✅
- [x] **Phase 4: Inventory operations**: traceable stock at bin level (`v0.4.0`) ✅
- [x] **Phase 5: Order fulfillment**: complete order lifecycle, returns and supplier purchase orders (`v0.5.0`) ✅
- [x] **Phase 6: Dashboards & reporting**: role-specific KPI dashboards, reports and CSV export (`v0.6.0`) ✅
- [x] **Phase 7: Synthetic data platform**: large, realistic, validated two-year dataset generated with one command (`v0.7.0`) ✅
- [x] **Phase 8: ML experimentation**: baselines and TensorFlow/Keras models trained, compared and registered for all six use cases (`v0.8.0`) ✅
- [x] **Phase 9: ML application integration**: predictions of the selected models inside the application, with approve/reject, purchase-order drafts and checks against reality (`v0.9.0`) ✅
- [ ] **Phase 10: Hardening, CI/CD & documentation**: final tested and documented platform (`v1.0.0`) 🚧 *in progress: test coverage in CI (backend 97 %, frontend 92 % of lines), end-to-end business scenarios (`backend/tests/integration/`), whole-app flows (`frontend/tests/`: login, roles, logout, session restore and expiry) a check that every API call of the web app matches a backend route, and the security review ([docs/security.md](docs/security.md): failed-login limit, security headers, strict CORS, clean server errors, security lint rules, weekly dependency audits) done; speed check with the full dataset ([docs/performance.md](docs/performance.md): all 44 page calls within limits on 500,000 orders, e.g. stock history 6 s → 22 ms, order search 1.4 s → 33 ms) done; ML checks and workflows (`scripts/check_models.py` in ML CI: models load, predictions complete and valid; *Train models* workflow started by hand, reports and models as downloads) done; release workflow (*Delivery*: every push builds and smoke-tests the package; a version tag runs all tests and publishes a GitHub Release) done; documentation ([docs/](docs/README.md): user guide, architecture, API with generated endpoint list and OpenAPI file, database with generated diagrams and table reference, ML) done; demo ([docs/demo-scenario.md](docs/demo-scenario.md) and `scripts/prepare_demo.py`: one command for a demo database with linked demo logins and trained, scored and checked models; screenshots; audit-log filters that list every action) done; final release next*

---

## Repository Structure

```
.
├── .github/workflows/
│   ├── backend-ci.yml        # lint, test, migrate and smoke-test the API
│   ├── frontend-ci.yml       # lint, type-check, test and build the UI
│   ├── ml-ci.yml             # lint and test the data generator, quick training, scoring and backtest
│   ├── security.yml          # dependency audits (pip-audit, npm audit): on changes and weekly
│   ├── delivery.yml          # build and smoke-test the release package; on a version tag: publish it
│   └── train-models.yml      # full training run, started by hand; reports and models as downloads
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI application (CORS, error handlers, /api/v1 router)
│   │   ├── core/             # settings (.env), logging, security (hashing, JWT), permissions
│   │   ├── database/         # SQLAlchemy base, engine, session and UTC datetime type
│   │   ├── models/           # ORM tables: users & roles, catalog, warehouse layout, inventory & movements, audit log & alerts
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── repositories/     # database queries (no business rules)
│   │   ├── services/         # business logic (auth, users, catalog, layout, inventory, approvals, cycle counts, alerts, audit)
│   │   ├── exceptions/       # application errors → JSON responses
│   │   └── api/              # dependencies, access rules and v1 endpoints (health, auth, users, catalog, warehouses, inventory, cycle counts, alerts, audit)
│   ├── migrations/           # Alembic database migrations
│   ├── tests/                # Pytest tests (temporary test database); integration/: business scenarios
│   ├── alembic.ini
│   ├── pyproject.toml        # Ruff, Black and Pytest settings
│   ├── requirements.txt      # runtime dependencies
│   └── requirements-dev.txt  # + test and quality tools
├── frontend/
│   ├── src/
│   │   ├── api/              # Axios client (token + auto-refresh), typed API calls
│   │   ├── components/       # DataTable, Modal, form fields…; layout/, products/, suppliers/, warehouse/, users/, inventory/
│   │   ├── context/          # AuthProvider (current user, login, logout), ToastProvider
│   │   ├── hooks/            # useAuth, useApiQuery / useApiMutation (TanStack Query), useUrlState, useToast
│   │   ├── layouts/          # AuthLayout (login) and DashboardLayout (sidebar + top bar)
│   │   ├── pages/            # Login, Dashboard, Products, Suppliers, Warehouse layout, Inventory, Cycle count, Alerts, Users, Audit log, 403, 404
│   │   ├── routes/           # AppRoutes and ProtectedRoute
│   │   ├── types/            # TypeScript types mirroring API schemas
│   │   ├── utils/            # helpers (roles, permissions, formatting, API errors)
│   │   ├── test/             # Vitest setup, fixtures, render helpers, apiRoutes.json (backend routes)
│   │   └── App.tsx
│   ├── tests/                # whole-app flows against a fake backend (login, roles, logout, sessions)
│   ├── package.json
│   └── vite.config.ts / vitest.config.ts / eslint.config.js
├── ml/
│   ├── data_generation/      # synthetic data: sizes and seed, patterns, master data, layout, day-by-day simulation, purchasing, orders, fulfillment, shipping, returns
│   ├── data_validation/      # dataset checks (integrity, volume, business patterns); reports/ holds the full-dataset report
│   ├── configs/              # YAML settings: common.yaml (seed, split, training) + one file per use case
│   ├── feature_engineering/  # feature tables per use case and their schemas
│   ├── baselines/            # simple baselines each model must beat
│   ├── models/               # Keras architectures per use case
│   ├── training/             # data extraction, chronological splits, configs, Keras setup
│   ├── evaluation/           # metrics for all six use cases; reports/ holds the model comparisons
│   ├── registry/             # register trained models and select the best per use case
│   ├── inference/            # predictors: the selected models score the latest data
│   ├── artifacts/            # saved .keras models (created when training, not committed)
│   ├── tests/                # Pytest tests of the generator and the ML code
│   ├── pyproject.toml        # Ruff, Black and Pytest settings
│   └── requirements.txt      # backend packages + NumPy, pandas, scikit-learn, TensorFlow
├── scripts/
│   ├── create_admin.py       # create the first administrator
│   ├── generate_data.py      # generate, load and validate the two-year synthetic dataset
│   ├── train_models.py       # train and compare the models of all six ML use cases
│   ├── score_models.py       # score all use cases into the prediction tables (--backtest DAYS: check them)
│   ├── export_api_routes.py  # list the backend routes for the frontend tests (frontend/src/test/apiRoutes.json)
│   ├── benchmark_api.py      # speed check: time the API behind every page on a (large) database
│   ├── check_models.py       # check the selected models load and their predictions are valid
│   ├── build_release.py      # build the release zip (project + built web app + install guide + checksum)
│   ├── generate_docs.py      # regenerate docs/openapi.json and the reference parts of api.md and database.md
│   ├── prepare_demo.py       # one command: demo dataset and logins, trained, scored and checked models
│   ├── take_screenshots.mjs  # take the README screenshots of the running platform (Playwright)
│   └── seed_database.py      # load demo data (users, catalog, suppliers, warehouse layout, stock)
├── docs/                     # documentation (index: docs/README.md)
│   ├── user-guide.md         # what each role does in the web app, step by step
│   ├── architecture.md       # the parts of the platform and how they work together
│   ├── api.md, openapi.json  # the API: login, roles, conventions, every endpoint (generated list)
│   ├── database.md           # design rules, diagrams and every table (generated reference)
│   ├── ml.md                 # the six ML use cases from data to dashboard
│   ├── demo-scenario.md      # a 12–15 minute walkthrough for a presentation
│   ├── screenshots/          # the screenshots in this README (scripts/take_screenshots.mjs)
│   ├── security.md           # security review: each rule, how it is met, which test checks it
│   └── performance.md        # speed check on the full dataset: what was slow, the fixes, results
├── database/                 # local SQLite file (warehouse.db is not committed)
├── .env.example              # environment template (copy to .env)
└── LICENSE
```

Planned for the rest of Phase 10: the final release (`v1.0.0`).

---

## Getting Started

### Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Git | any recent | `git --version` |
| Python | 3.12 | `python --version` |
| Node.js | 22.22+ (22 or 24 LTS) | `node --version` |

### 1. Clone the repository

```bash
git clone https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform.git
cd Digital-Warehouse-Operations-and-Fulfillment-Platform
```

### 2. Create the environment file

```bash
# Windows (PowerShell)
Copy-Item .env.example .env

# macOS / Linux
cp .env.example .env
```

The defaults work for local development. For anything beyond local development, set a strong `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### 3. Backend setup

```bash
# Create and activate a virtual environment (in the project root)
# Windows (PowerShell)
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# macOS / Linux
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements-dev.txt

# Create / upgrade the database
cd backend
alembic upgrade head
cd ..

# Create the first administrator (asks for email, name and a hidden password)
python scripts/create_admin.py

# Optional: load demo data (products, suppliers, warehouse layout, stock, demo users)
python scripts/seed_database.py

# Start the API
cd backend
uvicorn app.main:app --reload
```

- Health check: <http://localhost:8000/api/v1/health>
- Interactive API docs (Swagger): <http://localhost:8000/docs>. Log in with `POST /api/v1/auth/login`, then click **Authorize** and paste the `access_token` to call protected endpoints.

### 4. Frontend setup (in a second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173> and sign in with your admin account (or a [demo login](#demo-data)). Administrators create more users on the **Users** page; sign in with different roles to see how the navigation and permissions change.

---

## Testing & Code Quality

### Backend (from `backend/`, with the virtual environment active)

```bash
pytest -v                   # run tests (unit, API and tests/integration/ business scenarios)
pytest --cov                # with test coverage: files with gaps and the lines they miss
pytest tests/integration    # only the end-to-end scenarios
ruff check .                # lint
black --check .             # format check (use `black .` to auto-format)
```

### Data generation and ML (from `ml/`)

```bash
pytest -v          # run tests (generator, validation, features, baselines, models, training runs)
ruff check .       # lint
black --check .    # format check
```

### Frontend (from `frontend/`)

```bash
npm test               # run tests (Vitest): src/ components and pages, tests/ whole-app flows
npm run test:coverage  # with test coverage (report in coverage/index.html)
npm run lint           # ESLint
npm run typecheck      # TypeScript
npm run format:check   # Prettier (use `npm run format` to auto-format)
npm run build          # production build
```

### Speed check (from the project root)

```bash
python scripts/benchmark_api.py --database database/warehouse_synthetic.db
```

Times the API calls behind every page on a generated dataset and flags any call over 500 ms (reports over 90 days: 1 s). Results on the full dataset: [docs/performance.md](docs/performance.md).

### Continuous Integration

Every push and pull request to `main` runs **GitHub Actions**:

| Workflow | Runs when | Steps |
|----------|-----------|-------|
| Backend CI | `backend/**` or `scripts/**` changes | Ruff (with security rules) → Black → Pytest with coverage (fails below 96 %) → Alembic migrations → API smoke test |
| Frontend CI | `frontend/**` changes | ESLint → Prettier → TypeScript → Vitest with coverage (fails below 90 % of lines) → Vite build |
| ML CI | `ml/**`, `backend/**` or the data, training and scoring scripts change | Ruff → Black → Pytest → generate and validate the small dataset → train every use case quickly on it → score with the selected models → check the models and predictions → backtest |
| Security | dependency files change, every Monday, or by hand | pip-audit (backend and ML packages) → npm audit (production bundle, then everything) |
| Train models | started by hand (Actions tab) | generate a small, medium or full dataset → train and compare all six use cases → score → check → backtest → reports and models as downloads |
| Delivery | every push to `main`; version tags `v*.*.*` | build the web app → build the release zip → unpack it, migrate, load demo data, start the API, log in → on a tag: all test suites and the version check, then publish the GitHub Release |

---

## Development Workflow

- Work happens on the `main` branch, one small, reviewed step at a time.
- Run the tests and quality checks locally before every push.
- Each phase ends with green CI and a tagged release (`v0.1.0`, `v0.2.0`, …).

### Releases

Pushing a version tag publishes a release: the *Delivery* workflow runs all test suites, checks that the tag matches the version in the code, builds and smoke-tests the package, and attaches it to a GitHub Release.

```bash
git tag -a v1.0.0 -m "Version 1.0.0"
git push origin v1.0.0
```

The package (`warehouse-platform-<version>.zip`) holds the project and the built web app, with `INSTALL.md` (how to run it) and `SHA256SUMS` (to verify the download). It contains no databases, `.env` files or trained models. To build the same package locally: `cd frontend; npm run build`, then from the project root `python scripts/build_release.py` (add `--version v1.0.0` for a release version).
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `test:`, `docs:`, `ci:`, `chore:`).

---

## Author

**Om Dipak Patil**, MSc AI & Data Science
