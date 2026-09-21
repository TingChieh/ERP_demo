# Sales Shipment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement atomic shipment of a pending sales order, including all-stock validation, stock decreases, outbound history, one receivable, and completion status.

**Architecture:** Add a POST ship route to the existing sales-order Blueprint. The route first reads every current Product.stock and validates the entire order without writes; only after all lines pass does it stage stock decreases, outbound transactions, one receivable, and order completion in one SQLAlchemy transaction. Any exception rolls back the complete session. The detail page displays the completed receivable and outbound history.

**Tech Stack:** Flask, Flask-SQLAlchemy, SQLAlchemy, SQLite, Jinja2, Bootstrap 5, pytest.

## Global Constraints

- Only `pending_shipment` sales orders may be shipped.
- Any insufficient item fails the complete shipment with no writes and the exact user-facing message “库存不足，无法出库”.
- Product.stock and InventoryTransaction are updated together; no one-sided inventory update is allowed.
- InventoryTransaction.quantity is positive, type is `outbound`, and balance_after is the post-shipment balance.
- AccountReceivable.amount equals SalesOrder.total_amount and status is `unpaid`.
- Repeated shipment attempts cannot change stock or create additional records.
- Do not implement collection, payment, partial shipment, reservation, returns, or multi-warehouse behavior.
- Document that SQLite demo concurrency locking is intentionally out of scope.

---

### Task 1: Add failing shipment tests

**Files:**
- Create: `tests/test_sales_shipment.py`

**Interfaces:**
- Consumes: the existing sales-order routes and models.
- Produces: tests for successful shipment, insufficient stock, repeated shipment, invalid state, completed detail, and transaction rollback.

- [ ] **Step 1: Create pending sales orders with one and multiple items.**
- [ ] **Step 2: Write assertions for stock, outbound history, receivable, status, duplicate protection, and rollback.**
- [ ] **Step 3: Run `.venv/bin/python -m pytest tests/test_sales_shipment.py -q` and confirm failure because the ship route is not implemented.**

### Task 2: Implement atomic ship behavior

**Files:**
- Modify: `routes/sales_orders.py`

**Interfaces:**
- Consumes: `SalesOrder`, `SalesOrderItem`, `Product`, `InventoryTransaction`, `AccountReceivable`.
- Produces: `POST /sales-orders/<id>/ship`.

- [ ] **Step 1: Reject draft, completed, and already-receivable orders before any inventory write.**
- [ ] **Step 2: Read every current stock balance and fail the whole request before writes if any line is insufficient.**
- [ ] **Step 3: Decrease all stocks and create matching outbound transactions with balance_after.**
- [ ] **Step 4: Create exactly one unpaid receivable from SalesOrder.total_amount and set status to completed.**
- [ ] **Step 5: Commit once and rollback on any exception.**
- [ ] **Step 6: Run the shipment tests and confirm they pass.**

### Task 3: Update the sales-order detail page and documentation

**Files:**
- Modify: `routes/sales_orders.py`
- Modify: `templates/sales_orders/detail.html`
- Modify: `README.md`

**Interfaces:**
- Consumes: ship route state and related outbound/receivable records.
- Produces: pending shipment button, completed status, receivable summary, outbound transaction table, and SQLite concurrency scope note.

- [ ] **Step 1: Query outbound transactions by related order number.**
- [ ] **Step 2: Show “确认出库” only for pending orders and “已完成出库” for completed orders.**
- [ ] **Step 3: Show receivable and outbound history for completed orders.**
- [ ] **Step 4: Run the complete suite, syntax check, and route listing.**

