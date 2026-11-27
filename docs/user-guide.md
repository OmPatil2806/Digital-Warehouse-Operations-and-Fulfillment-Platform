# User guide

What each person in the warehouse does with the platform, step by step. The menu on
the left shows only the pages your role may use.

## Logging in

Open the web app (for example `http://localhost:5173`) and sign in with your e-mail and
password. If you open a page before signing in, you return to it afterwards. After 5
wrong passwords the account is locked for 15 minutes; the login page says when to try
again. **Log out** is at the top right.

Demo logins (development only), all with the password `Demo-pass-123`:

| E-mail | Role |
|---|---|
| `admin@example.com` | Admin |
| `manager@example.com` | Manager |
| `staff@example.com` | Staff |
| `customer@example.com` | Customer |

## Who sees what

| Page | Customer | Staff | Manager | Admin |
|---|:-:|:-:|:-:|:-:|
| Dashboard | ✓ | ✓ | ✓ | ✓ |
| Orders (customers: My orders) | ✓ | ✓ | ✓ | ✓ |
| Shipments and returns | ✓ (own) | ✓ | ✓ | ✓ |
| Products, Warehouse layout, Inventory, Purchase orders | | ✓ | ✓ | ✓ |
| Fulfillment, Alerts, Reports, ML insights | | ✓ | ✓ | ✓ |
| Suppliers | | | ✓ | ✓ |
| Users, Audit log | | | | ✓ |

Seeing a page does not mean changing everything on it: staff read master data and
purchase orders but do not change them, and their stock losses wait for a manager.

---

## Customer

**Place an order**: Orders → **New order** → add products and quantities → **Place
order**, then **Confirm** it on the order's page: that reserves the stock for you. Until
then you can still cancel it.

**Follow it**: the order's page shows its status timeline and, once shipped, the
carrier, tracking number and tracking events. **My parcels** on the dashboard lists
recent shipments.

**Return something**: on a delivered order, **Open return**, choose the items and the
reason. The warehouse inspects them when they arrive.

You only ever see your own orders, shipments and returns.

---

## Staff (warehouse floor)

**Receive goods**
- From a supplier: Purchase orders → open the order → **Receive goods** → quantities and
  bins → **Book into stock**. Orders waiting for these products are served first.
- Without a purchase order: Inventory → **Receive**, scan or type the bin code. The form
  checks that the bin has room (weight and volume).

**Pick and pack**: Fulfillment.
1. **Picking**: the queue lists the stops of each order as a walking route (farthest
   racks first). **Start**, go to the bin, confirm the bin code and the product, enter
   the quantity found (a short pick asks for a reason).
2. **Packing & shipping**: **Start packing**, check the items, enter parcels and weight,
   **Pack**; then **Ship** with the carrier (a tracking number is created if you leave it
   empty).

**Track parcels**: Shipments → open a shipment → add tracking events (in transit, out
for delivery, delayed, delivered). A delayed event raises an alert; delivery resolves it.

**Inspect returns**: Shipments → **Returns** → **Inspect**: per item *restock* (back into a
bin) or *damaged* (kept apart, not sold).

**Move and correct stock**: Inventory.
- **Move** units between bins. Within a warehouse it happens at once; to another
  warehouse it waits for a manager.
- **Adjust**: found units are added at once; lost, damaged or written-off units become a
  request a manager approves. **My requests** shows their status; you may withdraw them.
- **Cycle counts**: **Start count** on a bin, enter what you count, **Save counts**,
  **Submit for approval**.

**Look things up**: Inventory → **Stock** (search by product or bin), **Movement
history**; Warehouse layout → **Find bin**; product pages show stock per bin, the demand
forecast and related products.

---

## Manager

Everything staff can do, plus:

**Approve**: Inventory → **Approvals**: stock losses, transfers between warehouses and
cycle counts (**Approve**, **Reject** with a note, or **Send back for recount**).

**Orders**: create orders for any customer; **Confirm**, **Hold** / **Release**,
**Cancel** (with a reason); retry the reservation of an order waiting for stock.

**Buy stock**: Purchase orders → **New purchase order** (supplier, warehouse, products;
prices come from the supplier's offer) → **Save draft** → **Send to supplier**. **Check
overdue** raises alerts for late deliveries.

**Master data**: Products (**New product**, prices, minimum stock, default supplier),
Suppliers (**New supplier**, their products and prices), Warehouse layout (**New
warehouse**, **Create zone**, **Generate bins**).

**Act on alerts**: Alerts → **Acknowledge** ("I'm on it") or **Resolve**. Low-stock and
full-bin alerts close by themselves once the cause is gone.

**Watch the numbers**:
- Dashboard: stock value, open orders, shipments, on-time delivery, alerts, purchase
  orders, and the ML box (predicted stockouts, high-risk deliveries, coming demand with
  the latest forecast error, slotting moves).
- Reports: Inventory, Fulfillment, Warehouse and Suppliers, for any period, each table
  with **Export CSV**.

**Use the ML recommendations**: ML insights.
- **Reorder**: products likely to run out within 14 days, with order-by date, quantity
  and reasons. **Approve** drafts a purchase order with the product's supplier
  ("Draft purchase order created"); check and send it from Purchase orders.
- **Slotting**: better bins for fast movers; approve or reject each move.
- **Delay risk**: parcels on their way, most likely late first, with reasons.
- **Movement**: fast, medium and slow movers. **Models**: the model of each use case,
  its test result, and how the latest predictions compared with what happened.

Staff see ML insights too, without the approve and reject buttons.

---

## Admin

Everything, plus:

**Users**: **New user** (name, e-mail, roles, a first password), **Edit**, **Reset
password**, deactivate (their sessions end at once). A customer login is linked to its
customer record so the customer sees their own orders.

**Audit log**: who changed what and when, with the old and new values; filter by
**Record type** and **Action** (ML decisions appear as `ml.reorder.approve` and similar).

**Run the ML pipeline** (command line, see [ml.md](ml.md)): generate data, train, score
and check; or start *Train models* on GitHub.

---

## Problems and answers

| What you see | What it means |
|---|---|
| "Access denied" | your role may not open this page |
| "Too many failed login attempts. Try again in 15 minutes." | wait, or ask an admin to check the account |
| A form refuses a bin | the bin is full (weight or volume) or the wrong zone for the product |
| An order stays "partially allocated" | stock is missing; it is reserved automatically when goods arrive |
| "Something went wrong on the server (reference …)" | give the reference to the administrator; the details are in the server log |
| No ML numbers on the dashboard | the models have not been trained and scored yet |
