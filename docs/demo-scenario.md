# Demo scenario

A 12–15 minute walkthrough for a presentation. One story runs through the four roles: a
customer orders, the warehouse floor fulfils the order, the manager acts on the ML
recommendations, and the admin sees the trail. Each step lists what to click and what to
point out.

## Before the presentation (once, about 30 minutes ahead)

```bash
python scripts/prepare_demo.py                # medium dataset, full training
```

It generates the data (two years, 50,000 orders, 500 products) with the demo logins,
trains and compares all six ML use cases, scores them, checks the models and backtests
the last 30 days. Measured on a 4-core PC: 26 minutes (1.5 for the data, 24 for the
training, under a minute for the rest). At the end it prints the three things to do:

1. In `.env`: `DATABASE_URL=sqlite:///./database/warehouse_demo.db`
2. Start the API: `cd backend`, then `uvicorn app.main:app --port 8000`
3. Start the web app: `cd frontend`, then `npm run dev`, and open http://localhost:5173

All logins use the password `Demo-pass-123`. Open two browser windows (one of them
private) so you can stay logged in as two roles at once, for example customer and staff.

**Rehearse once.** With `--size small` the preparation takes about 6 minutes, enough to
try the clicks.

## The story

### 1. The problem (1 minute)

On the README: the problems the platform addresses (P1 to P8) and the architecture
diagram in [architecture.md](architecture.md). Say: "a digital warehouse from goods
receipt to shipment, with six ML models that help decide, each compared with a simple
baseline."

### 2. The customer orders (2 minutes)

Log in as **customer@example.com**.

- Dashboard: **My recent orders** and **My parcels**. This customer has a long history,
  only their own.
- Orders → **New order** → add two products and quantities → **Place order**.
- On the order page: **Confirm order**. Point out the status timeline: *created →
  confirmed → inventory reserved*. The stock is now held for this customer.
- Write down the order number.

Point out: customers see only their own orders; any other order number answers
"not found".

### 3. The warehouse floor (3 minutes)

In the other window, log in as **staff@example.com**.

- Orders → search the order number → **Create picking route**.
- Fulfillment → **Picking**: the stops appear as a walking route (farthest racks first,
  ending at packing). For each stop **Start**, confirm the bin code and the product (as a
  scanner would), enter the quantity.
- **Packing & shipping**: **Start packing**, enter parcels and weight, **Pack**, then
  **Ship** with a carrier. A tracking number is created.
- Back in the customer's window: refresh the order. It is **shipped**, with the carrier
  and tracking number.

Point out: every unit that left a shelf is an immutable stock movement (Inventory →
**Movement history**); picking checks the bin and product codes.

### 4. The manager decides, with ML (4–5 minutes)

Log in as **manager@example.com**.

- **Dashboard**: stock value, open orders, on-time delivery, alerts, purchase orders, and
  the **ML insights** box (predicted stockouts, high-risk deliveries, demand of the next
  7 days with the latest forecast error, slotting moves).
- **ML insights → Reorder**: the product most likely to run out within 14 days, with its
  order-by date, quantity and the reasons. **Approve** it: "Draft purchase order
  created".
- **Purchase orders**: open the new draft (supplier and price filled in from the
  supplier's offer, at least their minimum quantity) → **Send to supplier** → **Receive
  goods** → choose a bin → **Book into stock**. Stock rises and the low-stock alert
  closes by itself.
- **A product page** (click the product): stock per bin, the 30-day **demand forecast**
  with its likely range, the movement class, and **frequently bought together**.
- **ML insights → Models**: the model of each use case and its test result, and
  **predictions vs reality**: the forecast made 30 days before the end, compared with
  what customers then ordered (forecast error, share inside the range), and how many
  parcels of each risk level arrived late.
- **Reports → Inventory**: a report for any period, **Export CSV**.

Point out the honesty of the comparison: where a simple rule is as good (movement
classes, related products), the baseline is used; the delay model is weak because
delays are mostly chance in this data, and the app says so.

### 5. The admin and the trail (1–2 minutes)

Log in as **admin@example.com**.

- **Audit log**, filter **Action** `ml.reorder.approve`: the manager's decision, who and
  when. Every change to business data is recorded with its old and new values.
- **Users**: roles, deactivating a login ends its sessions at once.

### 6. How it is built and checked (2 minutes)

On GitHub:

- The README badges: Backend, Frontend and ML CI, Security, all green; tests with
  coverage minimums (backend 97 %, frontend 92 % of lines).
- **Actions**: *Train models* (a full training run by hand), *Delivery* (the release
  package is built and smoke-tested on every push).
- **Releases**: v1.0.0 with the package and its checksum.
- **docs/**: user guide, architecture, API, database diagrams, ML, security review,
  speed check (all 44 page calls within their limits on 500,000 orders).

## Questions you may get

| Question | Short answer (details) |
|---|---|
| Is the data real? | Generated: a two-year simulation with built-in business patterns, validated ([ml.md](ml.md)) |
| Why not always the neural network? | Each one must beat its baseline on unseen data ([ml.md](ml.md)) |
| How do you avoid data leakage? | Chronological split; features only from the past ([ml.md](ml.md)) |
| How is it secured? | Hashed passwords, short tokens, roles on every endpoint, failed-login limit ([security.md](security.md)) |
| Is it fast with lots of data? | Yes, measured on 500,000 orders ([performance.md](performance.md)) |
| Could it run for real? | One server with SQLite; many users would call for PostgreSQL ([architecture.md](architecture.md)) |

## If something goes wrong

| Problem | Fix |
|---|---|
| A login is locked (5 wrong passwords) | restart the API (the counter is kept in memory) or wait 15 minutes |
| The ML box says "No predictions yet" | `.env` points to another database; check `DATABASE_URL`, restart the API |
| The customer sees "Access denied" on orders | the database was not made by `prepare_demo.py` / `generate_data.py`; run it again |
| Start again from scratch | `python scripts/prepare_demo.py --replace` |
