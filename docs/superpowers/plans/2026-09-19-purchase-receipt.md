# Purchase Receipt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement atomic confirmation of a pending purchase order, including stock balance updates, inbound history, one payable, and completion status.

**Architecture:** Add a POST receive route to the existing purchase-order Blueprint. The route validates the order state, updates every product, inserts every inbound transaction and one payable in the same SQLAlchemy session, changes the order to completed, and commits once; any exception rolls back the whole session. The detail page queries related inbound transactions by order number and displays the payable after completion.

**Tech Stack:** Flask, Flask-SQLAlchemy, SQLAlchemy, SQLite, Jinja2, Bootstrap 5, pytest.

## Global Constraints

- Only `pending_receipt` purchase orders may be received.
- One receive request updates every item, creates every inbound transaction, creates one payable, and completes the order in one transaction.
- Product.stock and InventoryTransaction are updated together; no one-sided inventory update is allowed.
- InventoryTransaction.quantity is positive, type is `inbound`, and balance_after is the post-receipt balance.
- AccountPayable.amount equals PurchaseOrder.total_amount and status is `unpaid`.
- Repeated receipt attempts cannot change stock or create additional records.
- Do not implement payments, sales, returns, partial receipt, or multi-warehouse behavior.

---

### Task 1: Add failing receipt tests

**Files:**
- Create: `tests/test_purchase_receipt.py`

**Interfaces:**
- Consumes: the existing purchase-order routes and models.
- Produces: tests for successful receipt, repeated receipt, invalid state, detail display, and transaction rollback.

- [ ] **Step 1: Create pending purchase orders with one and multiple items.**
- [ ] **Step 2: Write assertions for stock, inbound history, payable, status, duplicate protection, and rollback.**
- [ ] **Step 3: Run `.venv/bin/python -m pytest tests/test_purchase_receipt.py -q` and confirm failure because the receive route is not implemented.**

### Task 2: Implement atomic receive behavior

**Files:**
- Modify: `routes/purchase_orders.py`

**Interfaces:**
- Consumes: `PurchaseOrder`, `PurchaseOrderItem`, `Product`, `InventoryTransaction`, `AccountPayable`.
- Produces: `POST /purchase-orders/<id>/receive`.

- [ ] **Step 1: Reject draft, completed, and already-payable orders before any inventory write.**
- [ ] **Step 2: Update all product balances and create matching inbound transactions with balance_after.**
- [ ] **Step 3: Create exactly one unpaid payable from PurchaseOrder.total_amount and set status to completed.**
- [ ] **Step 4: Commit once and rollback on any exception.**
- [ ] **Step 5: Run the receipt tests and confirm they pass.**

### Task 3: Update the purchase-order detail page

**Files:**
- Modify: `routes/purchase_orders.py`
- Modify: `templates/purchase_orders/detail.html`

**Interfaces:**
- Consumes: receive route state and related inventory/payable records.
- Produces: pending receipt button, completed status, payable summary, and inbound transaction table.

- [ ] **Step 1: Query inbound transactions by related order number.**
- [ ] **Step 2: Show “确认入库” only for pending orders and “已完成入库” for completed orders.**
- [ ] **Step 3: Show payable and inventory history for completed orders.**
- [ ] **Step 4: Run the complete suite, syntax check, and route listing.**

