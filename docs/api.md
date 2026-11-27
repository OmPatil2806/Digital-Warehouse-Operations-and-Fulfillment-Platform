# API

The backend is a REST API (FastAPI) under `/api/v1`. While it runs, the interactive
documentation is at `http://localhost:8000/docs` (try any call there) and
`http://localhost:8000/redoc`. The same description is saved in
[openapi.json](openapi.json) (OpenAPI 3) for other tools, such as client generators.

## Logging in

1. `POST /api/v1/auth/login` with `{"email": "...", "password": "..."}` returns an access
   token (valid 30 minutes) and sets a refresh-token cookie (`httpOnly`, 7 days, sent
   only to `/api/v1/auth`).
2. Every other call sends the token: `Authorization: Bearer <access token>`.
3. When it expires (`401`), `POST /api/v1/auth/refresh` returns a new one. The refresh token
   is replaced each time; presenting an old one again ends all sessions of that user.
4. `POST /api/v1/auth/logout` ends the session.

After 5 wrong passwords within 15 minutes an account is locked for 15 minutes
(`429 Too Many Requests` with `Retry-After`). See [security.md](security.md).

## Roles

Every endpoint except `GET /health` and the login, refresh and logout calls needs a
token. On top of that each endpoint checks the role; admins pass every check.

| Role | Can use |
|---|---|
| Customer | the catalog (active products, no costs), their own orders, shipments and returns, related products |
| Staff | reading everything in the warehouse; receiving, moving, picking, packing, shipping, cycle counts; stock losses and transfers between warehouses wait for a manager |
| Manager | all of staff, plus master data, approvals, orders for any customer, purchase orders, ML decisions |
| Admin | everything, plus users and the audit log |

A record the user may not see answers `404` (customers cannot find out that other
customers' orders exist); an action the role may not take answers `403`.

## Conventions

- **Lists** are paged: `?offset=0&limit=50` (at most 200), answered as
  `{"items": [...], "total": 1234, "offset": 0, "limit": 50}`. Most lists take filters
  and a text search `q`.
- **Errors** are JSON: `{"detail": "Bin WH01-ZA-R01-S01-B01 is full"}`. Invalid input
  answers `422` with the field and the reason. An unexpected error answers `500` with a
  reference that appears in the server log, never with technical details.
- **Times** are UTC with an explicit offset (`2026-11-10T14:05:00Z`); **days** are
  `YYYY-MM-DD`. Dashboards take `date_from` / `date_to` (default: the last 30 days).
- **Money, weights and sizes** are exact decimals, sent as strings (`"19.99"`).
- Status changes follow fixed rules (for example an order is packed before it ships); a
  change that breaks them answers `409` with the reason.

## Endpoints

Generated from the code; the backend tests fail when this list is out of date.

<!-- generated:endpoints:start (scripts/generate_docs.py) -->

137 endpoints. 🔒 = needs a login token (`Authorization: Bearer ...`).

### Health

| | Method | Path | What it does |
|---|---|---|---|
|  | GET | `/api/v1/health` | Service health status |

### Authentication

| | Method | Path | What it does |
|---|---|---|---|
|  | POST | `/api/v1/auth/login` | Log in with email and password |
|  | POST | `/api/v1/auth/refresh` | Get a new access token using the refresh-token cookie |
|  | POST | `/api/v1/auth/logout` | Log out (revoke the refresh token of this browser) |
| 🔒 | GET | `/api/v1/auth/me` | Get the logged-in user |

### Users

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/users` | List users |
| 🔒 | POST | `/api/v1/users` | Create a user |
| 🔒 | GET | `/api/v1/users/{user_id}` | Get a user |
| 🔒 | PATCH | `/api/v1/users/{user_id}` | Update a user (only the fields sent are changed) |
| 🔒 | POST | `/api/v1/users/{user_id}/deactivate` | Deactivate a user and end all their sessions |

### Categories

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/categories` | List categories |
| 🔒 | POST | `/api/v1/categories` | Create a category |
| 🔒 | GET | `/api/v1/categories/{category_id}` | Get a category |
| 🔒 | PATCH | `/api/v1/categories/{category_id}` | Update, archive (is_active=false) or restore a category |

### Products

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/products` | List and search products |
| 🔒 | POST | `/api/v1/products` | Create a product |
| 🔒 | GET | `/api/v1/products/{product_id}` | Get a product |
| 🔒 | PATCH | `/api/v1/products/{product_id}` | Update, archive (is_active=false) or restore a product |
| 🔒 | GET | `/api/v1/products/{product_id}/suppliers` | Suppliers offering this product (preferred first) |

### Suppliers

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/suppliers` | List and search suppliers |
| 🔒 | POST | `/api/v1/suppliers` | Create a supplier |
| 🔒 | GET | `/api/v1/suppliers/{supplier_id}` | Get a supplier |
| 🔒 | PATCH | `/api/v1/suppliers/{supplier_id}` | Update, archive (is_active=false) or restore a supplier |
| 🔒 | GET | `/api/v1/suppliers/{supplier_id}/products` | Products offered by this supplier |
| 🔒 | POST | `/api/v1/suppliers/{supplier_id}/products` | Add a product to this supplier's offer |
| 🔒 | PATCH | `/api/v1/suppliers/{supplier_id}/products/{product_id}` | Update the supplier's terms for a product |
| 🔒 | DELETE | `/api/v1/suppliers/{supplier_id}/products/{product_id}` | Remove a product from this supplier's offer |

### Warehouse layout

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/warehouses` | List warehouses |
| 🔒 | POST | `/api/v1/warehouses` | Create Warehouse |
| 🔒 | GET | `/api/v1/warehouses/{warehouse_id}` | Get Warehouse |
| 🔒 | PATCH | `/api/v1/warehouses/{warehouse_id}` | Update Warehouse |
| 🔒 | GET | `/api/v1/warehouses/{warehouse_id}/layout` | Full tree (zones > racks > shelves > bins) with capacity totals |
| 🔒 | POST | `/api/v1/warehouses/{warehouse_id}/zones` | Create Zone |
| 🔒 | PATCH | `/api/v1/zones/{zone_id}` | Update Zone |
| 🔒 | POST | `/api/v1/zones/{zone_id}/generate` | Generate racks x shelves x bins in one step (all or nothing) |
| 🔒 | POST | `/api/v1/zones/{zone_id}/racks` | Create Rack |
| 🔒 | PATCH | `/api/v1/racks/{rack_id}` | Update Rack |
| 🔒 | POST | `/api/v1/racks/{rack_id}/shelves` | Create Shelf |
| 🔒 | PATCH | `/api/v1/shelves/{shelf_id}` | Update Shelf |
| 🔒 | POST | `/api/v1/shelves/{shelf_id}/bins` | Create Bin |
| 🔒 | GET | `/api/v1/bins` | Search bins by location code |
| 🔒 | GET | `/api/v1/bins/by-code/{location_code}` | Look up a bin by its location code (simulated barcode scan) |
| 🔒 | PATCH | `/api/v1/bins/{bin_id}` | Update Bin |
| 🔒 | GET | `/api/v1/bins/{bin_id}/fit` | Check whether a quantity of a product fits into a bin (on top of its contents) |

### Audit

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/audit-logs` | Search the audit log (newest first) |

### Inventory

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/inventory` | List stock per product and bin |
| 🔒 | GET | `/api/v1/inventory/products/{product_id}` | Stock of one product: totals and the bins that hold it |
| 🔒 | GET | `/api/v1/inventory/movements` | Movement history (newest first) |
| 🔒 | POST | `/api/v1/inventory/receive` | Receive goods into a bin |
| 🔒 | POST | `/api/v1/inventory/adjustments` | Adjust stock (found, lost, damaged, restored, written off) |
| 🔒 | GET | `/api/v1/inventory/adjustments` | List adjustments |
| 🔒 | POST | `/api/v1/inventory/adjustments/{adjustment_id}/approve` | Approve a pending adjustment (applies it) |
| 🔒 | POST | `/api/v1/inventory/adjustments/{adjustment_id}/reject` | Reject a pending adjustment |
| 🔒 | POST | `/api/v1/inventory/adjustments/{adjustment_id}/cancel` | Withdraw your own pending adjustment |
| 🔒 | POST | `/api/v1/inventory/transfers` | Move stock to another bin |
| 🔒 | GET | `/api/v1/inventory/transfers` | List transfers |
| 🔒 | POST | `/api/v1/inventory/transfers/{transfer_id}/approve` | Approve a pending transfer (moves the stock) |
| 🔒 | POST | `/api/v1/inventory/transfers/{transfer_id}/reject` | Reject a pending transfer |
| 🔒 | POST | `/api/v1/inventory/transfers/{transfer_id}/cancel` | Withdraw your own pending transfer |
| 🔒 | GET | `/api/v1/inventory/approvals` | Requests waiting for a manager (oldest first) |
| 🔒 | POST | `/api/v1/inventory/reservations` | Reserve stock (one reservation per bin used) |
| 🔒 | GET | `/api/v1/inventory/reservations` | List reservations |
| 🔒 | POST | `/api/v1/inventory/reservations/{reservation_id}/release` | Release a reservation (units become available again) |

### Cycle counts

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/cycle-counts` | List cycle counts (newest first) |
| 🔒 | POST | `/api/v1/cycle-counts` | Start counting a bin |
| 🔒 | GET | `/api/v1/cycle-counts/{count_id}` | Get a cycle count |
| 🔒 | PUT | `/api/v1/cycle-counts/{count_id}/lines` | Enter counted quantities (while the count is open) |
| 🔒 | POST | `/api/v1/cycle-counts/{count_id}/submit` | Submit for approval |
| 🔒 | POST | `/api/v1/cycle-counts/{count_id}/approve` | Approve: apply the differences to the stock |
| 🔒 | POST | `/api/v1/cycle-counts/{count_id}/reject` | Send back for a recount |
| 🔒 | POST | `/api/v1/cycle-counts/{count_id}/cancel` | Cancel a count |

### Alerts

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/alerts` | List alerts (newest first) |
| 🔒 | GET | `/api/v1/alerts/summary` | Number of unresolved alerts |
| 🔒 | POST | `/api/v1/alerts/{alert_id}/acknowledge` | Acknowledge an alert (someone is on it) |
| 🔒 | POST | `/api/v1/alerts/{alert_id}/resolve` | Resolve an alert by hand |

### Customers

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/customers` | List customers |
| 🔒 | POST | `/api/v1/customers` | Create |
| 🔒 | GET | `/api/v1/customers/me` | The customer of the logged-in user |
| 🔒 | GET | `/api/v1/customers/{customer_id}` | Get a customer |
| 🔒 | PATCH | `/api/v1/customers/{customer_id}` | Change a customer |

### Orders

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/orders` | List orders (customers: their own) |
| 🔒 | POST | `/api/v1/orders` | Place an order (customers for themselves, managers for any customer) |
| 🔒 | GET | `/api/v1/orders/{order_id}` | Get an order |
| 🔒 | POST | `/api/v1/orders/{order_id}/confirm` | Confirm and reserve |
| 🔒 | POST | `/api/v1/orders/{order_id}/cancel` | Cancel (before picking) |
| 🔒 | POST | `/api/v1/orders/{order_id}/hold` | Put on hold |
| 🔒 | POST | `/api/v1/orders/{order_id}/release` | Release the hold |
| 🔒 | POST | `/api/v1/orders/{order_id}/reserve` | Retry reserving missing units |
| 🔒 | POST | `/api/v1/orders/{order_id}/allocate` | Create the picking route (reserved -> allocated) |
| 🔒 | GET | `/api/v1/orders/{order_id}/picking-tasks` | The order's picking tasks in route order |

### Fulfillment

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/picking-tasks` | Picking work queue: urgent orders first, then along each order's route |
| 🔒 | POST | `/api/v1/picking-tasks/{task_id}/start` | Start picking |
| 🔒 | POST | `/api/v1/picking-tasks/{task_id}/complete` | Confirm a pick with the scanned bin and product |
| 🔒 | GET | `/api/v1/packing-tasks` | Packing work queue |
| 🔒 | POST | `/api/v1/packing-tasks/{task_id}/start` | Start packing |
| 🔒 | POST | `/api/v1/packing-tasks/{task_id}/complete` | Confirm what went into the parcels |

### Shipments

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/carriers` | Active carriers |
| 🔒 | GET | `/api/v1/shipments` | List shipments (newest first) |
| 🔒 | POST | `/api/v1/shipments` | Ship a packed order |
| 🔒 | POST | `/api/v1/shipments/check-delays` | Mark shipments past their expected delivery date as delayed |
| 🔒 | GET | `/api/v1/shipments/{shipment_id}` | Get |
| 🔒 | GET | `/api/v1/shipments/{shipment_id}/events` | Tracking timeline |
| 🔒 | POST | `/api/v1/shipments/{shipment_id}/events` | Add a tracking event (in transit, delayed, delivered, ...) |
| 🔒 | GET | `/api/v1/orders/{order_id}/shipment` | The order's shipment (null if not shipped yet) |

### Returns

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/returns` | List returns (customers: their own) |
| 🔒 | POST | `/api/v1/returns` | Open a return for a delivered order |
| 🔒 | GET | `/api/v1/returns/{return_id}` | Get a return |
| 🔒 | POST | `/api/v1/returns/{return_id}/inspect` | Receive and inspect |
| 🔒 | POST | `/api/v1/returns/{return_id}/cancel` | Cancel an open return |

### Purchase orders

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/purchase-orders` | List purchase orders |
| 🔒 | POST | `/api/v1/purchase-orders` | Draft a purchase order |
| 🔒 | POST | `/api/v1/purchase-orders/check-overdue` | Raise alerts for purchase orders past their expected date |
| 🔒 | GET | `/api/v1/purchase-orders/{po_id}` | Get a purchase order |
| 🔒 | POST | `/api/v1/purchase-orders/{po_id}/order` | Send the order to the supplier |
| 🔒 | POST | `/api/v1/purchase-orders/{po_id}/cancel` | Cancel |
| 🔒 | POST | `/api/v1/purchase-orders/{po_id}/receive` | Receive goods into bins |

### Dashboards

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/dashboards/overview` | Headline KPIs |
| 🔒 | GET | `/api/v1/dashboards/inventory` | Stock value, status, turnover and days of supply |
| 🔒 | GET | `/api/v1/dashboards/fulfillment` | Orders per day, fulfillment speed, on-time delivery, picking accuracy |
| 🔒 | GET | `/api/v1/dashboards/warehouse` | Bin occupancy, space use and picks per zone |
| 🔒 | GET | `/api/v1/dashboards/suppliers` | Supplier lead times, their variance and on-time delivery |

### ML predictions

| | Method | Path | What it does |
|---|---|---|---|
| 🔒 | GET | `/api/v1/ml/models` | Selected models |
| 🔒 | GET | `/api/v1/ml/accuracy` | Predictions vs reality: the latest checkable forecast and delay risks |
| 🔒 | GET | `/api/v1/ml/summary` | Headline ML numbers |
| 🔒 | GET | `/api/v1/ml/demand-forecasts/{product_id}` | Demand forecast of a product (next 30 days, with range) |
| 🔒 | GET | `/api/v1/ml/reorder-recommendations` | Products at risk of running out (latest scoring, highest risk first) |
| 🔒 | POST | `/api/v1/ml/reorder-recommendations/{recommendation_id}/approve` | Approve a reorder recommendation (drafts a purchase order) |
| 🔒 | POST | `/api/v1/ml/reorder-recommendations/{recommendation_id}/reject` | Reject a reorder recommendation |
| 🔒 | GET | `/api/v1/ml/movement-classification/{product_id}` | Fast, medium or slow mover |
| 🔒 | GET | `/api/v1/ml/movement-classifications` | Movement classes (latest scoring, most picked first) |
| 🔒 | GET | `/api/v1/ml/movement-classifications/summary` | Number of fast, medium and slow movers and their share of picks |
| 🔒 | GET | `/api/v1/ml/slotting-recommendations` | Better pick locations (latest scoring, biggest time saving first) |
| 🔒 | POST | `/api/v1/ml/slotting-recommendations/{recommendation_id}/approve` | Approve a slotting recommendation |
| 🔒 | POST | `/api/v1/ml/slotting-recommendations/{recommendation_id}/reject` | Reject a slotting recommendation |
| 🔒 | GET | `/api/v1/ml/delay-risk/{order_id}` | Late-delivery risk of an order's shipment (null when not on its way) |
| 🔒 | GET | `/api/v1/ml/delay-risks` | Shipments on their way by delay risk (latest scoring, highest first) |
| 🔒 | GET | `/api/v1/ml/product-recommendations/{product_id}` | Products often bought together with this one |

<!-- generated:endpoints:end -->
