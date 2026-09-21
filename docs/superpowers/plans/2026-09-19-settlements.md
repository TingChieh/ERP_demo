# Receivables and Payables Settlement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full-settlement list and confirmation actions for receivables and payables without changing inventory or order fulfillment state.

**Architecture:** Add one small server-rendered settlements Blueprint with separate receivable/payable list routes and POST confirmation routes. Each action updates only the selected financial record's status and paid_at in one database commit; templates expose no amount or relationship edit controls. Existing Dashboard aggregate queries remain database-backed and show unpaid balances.

**Tech Stack:** Flask, Flask-SQLAlchemy, SQLAlchemy, SQLite, Jinja2, Bootstrap 5, pytest.

## Global Constraints

- Do not implement partial payment, multiple payment, invoices, reconciliation, refunds, returns, cash flow, or bank accounts.
- Only `unpaid` receivables/payables may be settled.
- Settlement changes only status and paid_at; amount, order links, stock, inventory history, and order fulfillment status remain unchanged.
- Receivables and payables are settled in full in this MVP.
- Dashboard unpaid totals use `sum(amount)` filtered by `status='unpaid'`.

---

### Task 1: Add failing settlement tests

**Files:**
- Create: `tests/test_settlements.py`

**Interfaces:**
- Consumes: `create_app(config)`, the existing financial models, and future settlement routes.
- Produces: tests for both list pages, successful settlement, duplicate protection, no operational side effects, and Dashboard totals.

- [ ] **Step 1: Seed completed sales/purchase orders, unpaid and paid financial records, and a product stock balance.**
- [ ] **Step 2: Write tests for receivable and payable settlement rules.**
- [ ] **Step 3: Run `.venv/bin/python -m pytest tests/test_settlements.py -q` and confirm failure because the routes do not exist.**

### Task 2: Implement settlement routes

**Files:**
- Create: `routes/settlements.py`
- Modify: `app.py`

**Interfaces:**
- Consumes: AccountReceivable, AccountPayable, SalesOrder, PurchaseOrder, Product, and db.
- Produces: `GET /receivables`, `POST /receivables/<id>/receive-payment`, `GET /payables`, and `POST /payables/<id>/pay`.

- [ ] **Step 1: Implement read-only receivable and payable list queries.**
- [ ] **Step 2: Implement unpaid-to-paid transitions with current paid_at and guards for already-paid records.**
- [ ] **Step 3: Commit only the financial status/time change and rollback database failures.**
- [ ] **Step 4: Run settlement tests and confirm they pass.**

### Task 3: Update templates, related details, navigation, and Dashboard verification

**Files:**
- Modify: `templates/base.html`
- Create: `templates/receivables/list.html`
- Create: `templates/payables/list.html`
- Modify: `templates/sales_orders/detail.html`
- Modify: `templates/purchase_orders/detail.html`
- Modify: `README.md`

**Interfaces:**
- Consumes: settlement endpoint names and paid_at values from Task 2.
- Produces: list pages, payment buttons, paid-time display on completed order details, and working finance navigation.

- [ ] **Step 1: Add receivable and payable list templates with settlement actions only for unpaid records.**
- [ ] **Step 2: Show paid_at on completed sales and purchase order details.**
- [ ] **Step 3: Link the finance navigation and document the full-settlement scope.**
- [ ] **Step 4: Run the complete test suite, syntax check, and route listing.**

