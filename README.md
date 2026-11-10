# Digital Warehouse Operations and Fulfillment Platform

[![Backend CI](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/backend-ci.yml/badge.svg?branch=main)](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/backend-ci.yml)
[![Frontend CI](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/frontend-ci.yml/badge.svg?branch=main)](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/frontend-ci.yml)
![Version](https://img.shields.io/badge/version-v0.5.0-blue)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/node-22.22%2B-339933?logo=nodedotjs&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

A full-stack platform that digitises the core operations of a modern distribution warehouse, from goods receipt to shipment, and adds a machine-learning decision-support layer built with **TensorFlow/Keras**.

The platform manages products, suppliers, physical storage locations, inventory, customer orders, picking, packing, shipping and returns, and shows the state of the warehouse through role-based dashboards. On top of the operational system, six ML use cases help forecast demand, prevent stockouts, place products intelligently, warn about delayed orders and recommend related products. Every model is compared against a simple baseline.

> **Status:** 🚧 Under active development, built step by step in 10 phases.
> **Phase 5 (order fulfillment) is complete: `v0.5.0`.** See the [Roadmap](#roadmap).

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

| Role | Responsibilities | Sees in the app (pages arrive in later phases) |
|------|------------------|------------------------------------------------|
| **Admin** | Users, roles, settings, audit, ML models | Everything (admins pass every role check) |
| **Manager** | KPIs, approvals, ML recommendations | Products, Suppliers, Warehouse layout, Inventory, Orders, Fulfillment, Shipments, Alerts, ML insights |
| **Staff** | Receiving, picking, packing, scanning | Products, Warehouse layout, Inventory, Orders, Fulfillment, Shipments |
| **Customer** | Placing and tracking orders | Orders, Shipments |

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
        SQLite Database           ML Inference Layer
   operational, feature and     saved .keras models,
     prediction tables           prediction services
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
- [ ] **Phase 6: Dashboards & reporting**: KPI dashboards and alerts (`v0.6.0`) 🚧 *in progress: KPI APIs done (`/api/v1/dashboards/overview`, `/inventory`, `/fulfillment`, `/warehouse`, `/suppliers`) the chart building blocks (Recharts) and the role-specific home dashboard; detailed report pages next*
- [ ] **Phase 7: Synthetic data platform**: large, realistic dataset (`v0.7.0`)
- [ ] **Phase 8: ML experimentation**: trained and compared models for six use cases (`v0.8.0`)
- [ ] **Phase 9: ML application integration**: predictions inside the application (`v0.9.0`)
- [ ] **Phase 10: Hardening, CI/CD & documentation**: final tested and documented platform (`v1.0.0`)

---

## Repository Structure

```
.
├── .github/workflows/
│   ├── backend-ci.yml        # lint, test, migrate and smoke-test the API
│   └── frontend-ci.yml       # lint, type-check, test and build the UI
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
│   ├── tests/                # Pytest tests (temporary test database)
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
│   │   ├── test/             # Vitest setup, fixtures and render helpers
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts / vitest.config.ts / eslint.config.js
├── scripts/
│   ├── create_admin.py       # create the first administrator
│   └── seed_database.py      # load demo data (users, catalog, suppliers, warehouse layout, stock)
├── database/                 # local SQLite file (warehouse.db is not committed)
├── .env.example              # environment template (copy to .env)
└── LICENSE
```

Planned for later phases: `ml/` (data generation, features, models, training, evaluation) and `docs/`.

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
pytest -v          # run tests
ruff check .       # lint
black --check .    # format check (use `black .` to auto-format)
```

### Frontend (from `frontend/`)

```bash
npm test               # run tests (Vitest)
npm run lint           # ESLint
npm run typecheck      # TypeScript
npm run format:check   # Prettier (use `npm run format` to auto-format)
npm run build          # production build
```

### Continuous Integration

Every push and pull request to `main` runs **GitHub Actions**:

| Workflow | Runs when | Steps |
|----------|-----------|-------|
| Backend CI | `backend/**` or `scripts/**` changes | Ruff → Black → Pytest → Alembic migrations → API smoke test |
| Frontend CI | `frontend/**` changes | ESLint → Prettier → TypeScript → Vitest → Vite build |

---

## Development Workflow

- Work happens on the `main` branch, one small, reviewed step at a time.
- Run the tests and quality checks locally before every push.
- Each phase ends with green CI and a tagged release (`v0.1.0`, `v0.2.0`, …).
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `test:`, `docs:`, `ci:`, `chore:`).

---

## Author

**Om Dipak Patil**, MSc AI & Data Science
