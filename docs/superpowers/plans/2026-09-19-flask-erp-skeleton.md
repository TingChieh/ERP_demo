# Flask ERP Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a small Flask + SQLite ERP foundation with the confirmed data model, idempotent demo-data initialization, and a read-only Dashboard.

**Architecture:** Use a single Flask application with Flask-SQLAlchemy and server-rendered Jinja2 templates. Keep all models in `models.py`, database setup and seed data in `init_db.py`, and expose only the Dashboard route in `app.py`; later business workflows will be added separately.

**Tech Stack:** Flask, Flask-SQLAlchemy, SQLAlchemy, SQLite, Jinja2, Bootstrap 5, pytest.

## Global Constraints

- Product.stock is the current inventory balance and cannot be edited through an ordinary business page.
- InventoryTransaction records inventory history and includes balance_after.
- Inventory changes will later be implemented only by receipt or shipment workflows.
- Purchase receipt directly creates the payable in this MVP.
- SalesOrder completion means shipment fulfillment, not customer payment.
- Sales fulfillment status and receivable status remain independent.
- Do not implement receipt, shipment, collection, payment, authentication, or complex permissions in this step.

---

### Task 1: Add the skeleton acceptance tests

**Files:**
- Create: `tests/test_skeleton.py`

**Interfaces:**
- Consumes: `create_app(config)`, `db`, `initialize_database(app)`.
- Produces: tests that define the minimum runnable skeleton behavior.

- [ ] **Step 1: Write tests for app creation, schema creation, seed data, and Dashboard response.**
- [ ] **Step 2: Run `pytest -q` and confirm failure because the application modules do not exist yet.**

### Task 2: Implement the Flask application and confirmed models

**Files:**
- Create: `app.py`
- Create: `models.py`

**Interfaces:**
- Consumes: the expectations in `tests/test_skeleton.py`.
- Produces: `create_app(config=None)`, module-level `app`, and SQLAlchemy models for products, partners, orders, order items, inventory history, receivables, and payables.

- [ ] **Step 1: Implement the SQLAlchemy extension and all model columns, relationships, uniqueness rules, and non-negative inventory constraints.**
- [ ] **Step 2: Implement the read-only Dashboard route and its aggregate metrics.**
- [ ] **Step 3: Run `pytest -q` and confirm the tests pass.**

### Task 3: Add database initialization and demo data

**Files:**
- Create: `init_db.py`

**Interfaces:**
- Consumes: `create_app`, `db`, and the master-data models from `models.py`.
- Produces: idempotent `initialize_database(app)` and a runnable script entry point.

- [ ] **Step 1: Implement table creation and the two products, one supplier, and one customer.**
- [ ] **Step 2: Run `python init_db.py`.**
- [ ] **Step 3: Run `pytest -q` again and confirm the seeded-data assertions pass.**

### Task 4: Add templates, dependencies, and startup documentation

**Files:**
- Create: `templates/base.html`
- Create: `templates/dashboard.html`
- Create: `static/css/style.css`
- Create: `requirements.txt`
- Create: `README.md`

**Interfaces:**
- Consumes: Dashboard metrics supplied by `app.py`.
- Produces: Bootstrap 5 server-rendered UI, dependency list, and local startup instructions.

- [ ] **Step 1: Add a sidebar and Dashboard cards without links to unimplemented workflows.**
- [ ] **Step 2: Document virtualenv setup, dependency installation, database initialization, and app startup.**
- [ ] **Step 3: Run the full test suite and a manual HTTP smoke test.**

