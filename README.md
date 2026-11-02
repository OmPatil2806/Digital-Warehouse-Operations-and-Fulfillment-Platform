# Digital Warehouse Operations and Fulfillment Platform

[![Backend CI](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/backend-ci.yml/badge.svg?branch=main)](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/backend-ci.yml)
[![Frontend CI](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/frontend-ci.yml/badge.svg?branch=main)](https://github.com/OmPatil2806/Digital-Warehouse-Operations-and-Fulfillment-Platform/actions/workflows/frontend-ci.yml)
![Version](https://img.shields.io/badge/version-v0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Node](https://img.shields.io/badge/node-22_LTS-339933?logo=nodedotjs&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

A full-stack platform that digitises the core operations of a modern distribution warehouse, from goods receipt to shipment, and adds a machine-learning decision-support layer built with **TensorFlow/Keras**.

The platform manages products, suppliers, physical storage locations, inventory, customer orders, picking, packing, shipping and returns, and shows the state of the warehouse through role-based dashboards. On top of the operational system, six ML use cases help forecast demand, prevent stockouts, place products intelligently, warn about delayed orders and recommend related products. Every model is compared against a simple baseline.

> **Status:** 🚧 Under active development, built step by step in 10 phases.
> **Phase 1 (project foundation) is complete: `v0.1.0`.** See the [Roadmap](#roadmap).

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
- [ ] **Phase 2: Authentication & authorization**: secure login and role-based access (`v0.2.0`) ⏭️ *next*
- [ ] **Phase 3: Master data & warehouse layout**: products, suppliers and physical locations (`v0.3.0`)
- [ ] **Phase 4: Inventory operations**: traceable stock at bin level (`v0.4.0`)
- [ ] **Phase 5: Order fulfillment**: complete order lifecycle (`v0.5.0`)
- [ ] **Phase 6: Dashboards & reporting**: KPI dashboards and alerts (`v0.6.0`)
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
│   │   ├── main.py           # FastAPI application (CORS, /api/v1 router)
│   │   ├── core/             # settings (.env) and logging
│   │   ├── database/         # SQLAlchemy base, engine and session
│   │   └── api/v1/           # versioned REST endpoints (health)
│   ├── migrations/           # Alembic database migrations
│   ├── tests/                # Pytest tests (temporary test database)
│   ├── alembic.ini
│   ├── pyproject.toml        # Ruff, Black and Pytest settings
│   ├── requirements.txt      # runtime dependencies
│   └── requirements-dev.txt  # + test and quality tools
├── frontend/
│   ├── src/
│   │   ├── api/              # Axios client and typed API calls
│   │   ├── components/       # reusable UI components
│   │   ├── types/            # TypeScript types mirroring API schemas
│   │   ├── test/             # Vitest setup and test fixtures
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts / vitest.config.ts / eslint.config.js
├── database/                 # local SQLite file (warehouse.db is not committed)
├── .env.example              # environment template (copy to .env)
└── LICENSE
```

Planned for later phases: `ml/` (data generation, features, models, training, evaluation), `scripts/` and `docs/`.

---

## Getting Started

### Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Git | any recent | `git --version` |
| Python | 3.12 | `python --version` |
| Node.js | 20.19+ or 22 LTS | `node --version` |

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

The defaults work for local development. Change `SECRET_KEY` before any real use.

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

# Create / upgrade the database and start the API
cd backend
alembic upgrade head
uvicorn app.main:app --reload
```

- Health check: <http://localhost:8000/api/v1/health>
- Interactive API docs (Swagger): <http://localhost:8000/docs>

### 4. Frontend setup (in a second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The **System status** card shows **Online** when the backend and database are reachable.

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
| Backend CI | `backend/**` changes | Ruff → Black → Pytest → Alembic migrations → API smoke test |
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
