# Master Data Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add simple server-rendered CRUD pages for products, suppliers, and customers without implementing any ERP transaction workflow.

**Architecture:** Add one small Flask Blueprint per master-data type. Each Blueprint owns its list, create, and edit routes and renders a pair of simple Jinja templates; `app.py` only registers the Blueprints. Product forms never expose or assign `Product.stock`.

**Tech Stack:** Flask, Flask-SQLAlchemy, SQLAlchemy, SQLite, Jinja2, Bootstrap 5, pytest.

## Global Constraints

- Do not implement purchase orders, receipts, sales orders, shipments, receivables, payables, collection, or payment.
- Product.stock is display-only in ordinary product pages and new products start at 0.
- Product name and SKU are required; SKU is unique; purchase and sale prices must be non-negative.
- Supplier name and customer name are required.
- Do not implement deletion in this phase.
- Keep the UI server-rendered and readable by an undergraduate developer.

---

### Task 1: Add failing master-data tests

**Files:**
- Create: `tests/test_master_data.py`

**Interfaces:**
- Consumes: `create_app(config)`, `db`, and the routes `/products`, `/suppliers`, and `/customers`.
- Produces: tests for list pages, create flows, duplicate SKU rejection, and stock protection.

- [ ] **Step 1: Write tests for the six requested behaviors and one stock-edit protection behavior.**
- [ ] **Step 2: Run `.venv/bin/python -m pytest tests/test_master_data.py -q` and confirm the tests fail because the routes do not exist.**

### Task 2: Implement the three master-data Blueprints

**Files:**
- Create: `routes/__init__.py`
- Create: `routes/products.py`
- Create: `routes/suppliers.py`
- Create: `routes/customers.py`

**Interfaces:**
- Consumes: existing SQLAlchemy models and the tests from Task 1.
- Produces: list, create, and edit routes at `/products`, `/suppliers`, and `/customers`.

- [ ] **Step 1: Implement Product list/create/edit with server-side validation and no stock form field.**
- [ ] **Step 2: Implement Supplier list/create/edit with required-name validation.**
- [ ] **Step 3: Implement Customer list/create/edit with required-name validation.**
- [ ] **Step 4: Run the master-data tests and confirm they pass.**

### Task 3: Add templates and register navigation

**Files:**
- Modify: `app.py`
- Modify: `templates/base.html`
- Create: `templates/products/list.html`
- Create: `templates/products/form.html`
- Create: `templates/suppliers/list.html`
- Create: `templates/suppliers/form.html`
- Create: `templates/customers/list.html`
- Create: `templates/customers/form.html`

**Interfaces:**
- Consumes: Blueprint endpoint names and validation errors from Task 2.
- Produces: Bootstrap 5 master-data pages and working sidebar links.

- [ ] **Step 1: Register the three Blueprints in `create_app`.**
- [ ] **Step 2: Add working sidebar links for product, supplier, and customer management.**
- [ ] **Step 3: Add list and form templates without delete controls or inventory-edit controls.**
- [ ] **Step 4: Run the complete test suite and verify only the intended routes were added.**

