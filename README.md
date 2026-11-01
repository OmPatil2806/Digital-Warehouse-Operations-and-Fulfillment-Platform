# Digital Warehouse Operations and Fulfillment Platform

A full-stack platform that digitises the core operations of a modern distribution warehouse, from goods receipt to shipment, and adds a machine-learning decision-support layer built with **TensorFlow/Keras**.

The platform manages products, suppliers, physical storage locations, inventory, customer orders, picking, packing, shipping and returns, and shows the state of the warehouse through role-based dashboards. On top of the operational system, six ML use cases help forecast demand, prevent stockouts, place products intelligently, warn about delayed orders and recommend related products. Every model is compared against a simple baseline.

> **Status:** 🚧 Under active development, built step by step in 10 phases. See the [Roadmap](#roadmap).

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
| Frontend | React, TypeScript, Tailwind CSS, React Router, Axios, React Hook Form, Zod, Recharts |
| Backend | Python, FastAPI, SQLAlchemy, Alembic, Pydantic, JWT |
| Database | SQLite |
| Machine learning | TensorFlow, Keras, TensorFlow Recommenders, Pandas, NumPy, scikit-learn |
| Testing & quality | Pytest, HTTPX, Vitest, React Testing Library, Ruff, Black, ESLint, Prettier |
| DevOps | Git, GitHub, GitHub Actions (CI/CD) |

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

- [ ] **Phase 1: Project foundation**: running skeleton of frontend, backend, database and CI (`v0.1.0`) 🚧 *in progress*
- [ ] **Phase 2: Authentication & authorization**: secure login and role-based access (`v0.2.0`)
- [ ] **Phase 3: Master data & warehouse layout**: products, suppliers and physical locations (`v0.3.0`)
- [ ] **Phase 4: Inventory operations**: traceable stock at bin level (`v0.4.0`)
- [ ] **Phase 5: Order fulfillment**: complete order lifecycle (`v0.5.0`)
- [ ] **Phase 6: Dashboards & reporting**: KPI dashboards and alerts (`v0.6.0`)
- [ ] **Phase 7: Synthetic data platform**: large, realistic dataset (`v0.7.0`)
- [ ] **Phase 8: ML experimentation**: trained and compared models for six use cases (`v0.8.0`)
- [ ] **Phase 9: ML application integration**: predictions inside the application (`v0.9.0`)
- [ ] **Phase 10: Hardening, CI/CD & documentation**: final tested and documented platform (`v1.0.0`)

---

## Planned Repository Structure

```
.
├── .github/workflows/   # CI/CD pipelines
├── frontend/            # React + TypeScript + Tailwind app
├── backend/             # FastAPI app, models, services, tests
├── ml/                  # data generation, features, models, training, evaluation
├── scripts/             # database init, seeding, data generation
├── database/            # local SQLite database (not committed)
└── docs/                # architecture, API, database, ML and user guide
```

---

## Getting Started

Setup and run instructions will be added in **Phase 1**.

---

## Author

**Om Dipak Patil**, MSc AI & Data Science
