# 草稿订单修改与删除 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为采购订单和销售订单增加安全的草稿编辑、删除能力，并保持提交、入库、出库、应收应付及库存逻辑不变。

**Architecture:** 在 `services/orders.py` 增加采购/销售草稿更新和删除服务，复用现有订单明细标准化、金额计算和日志模式。采购和销售路由分别增加编辑、删除端点，并将现有新建表单模板参数化为新建/编辑两种模式；详情页只对 `draft` 显示操作按钮，服务层和路由层都强制校验状态。

**Tech Stack:** Flask、Flask-SQLAlchemy、Jinja2、SQLite 测试数据库、pytest、现有 Bootstrap/CSS 页面组件。

## Global Constraints

- 只有 `draft` 订单允许编辑或删除；`pending_receipt`、`pending_shipment`、`completed` 必须拒绝这些操作。
- 订单号和创建时间不可修改。
- 编辑必须重新校验供应商/客户、商品、数量、单价、重复商品和至少一条明细。
- 编辑必须由服务器重新计算总金额，不信任客户端金额。
- 删除只级联删除订单及其草稿明细，不修改库存、库存流水、应收或应付。
- 编辑或删除失败必须回滚，不产生部分数据变化。
- 不新增数据库字段，不修改已存在的状态流转和履约逻辑。
- 每个任务先写失败测试，再写最小实现；每个任务完成后运行对应测试并提交。

---

### Task 1: 增加草稿订单服务层更新与删除能力

**Files:**
- Modify: `services/orders.py`
- Test: `tests/test_purchase_orders.py`
- Test: `tests/test_sales_orders.py`

**Interfaces:**
- Consumes: 现有 `_normalize_lines`、订单模型关系和 `record_database_operation`。
- Produces:
  - `update_purchase_order_draft(order, supplier_id, lines, *, source="web") -> PurchaseOrder`
  - `delete_purchase_order_draft(order, *, source="web") -> None`
  - `update_sales_order_draft(order, customer_id, lines, *, source="web") -> SalesOrder`
  - `delete_sales_order_draft(order, *, source="web") -> None`

- [ ] **Step 1: Write failing service tests for purchase and sales updates.**

Add tests that create a draft and call the exact service signatures:

```python
def test_update_purchase_order_draft_replaces_lines_and_total(app, master_data):
    with app.app_context():
        order = create_purchase_order_draft(
            master_data["supplier_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "80"}],
        )
        updated = update_purchase_order_draft(
            order,
            master_data["supplier_id"],
            [{"product_id": master_data["mouse_id"], "quantity": 3, "unit_price": "35.50"}],
        )
        assert updated.status == "draft"
        assert updated.order_no == order.order_no
        assert len(updated.items) == 1
        assert updated.items[0].product_id == master_data["mouse_id"]
        assert updated.total_amount == Decimal("106.50")
```

Add the equivalent sales test using `update_sales_order_draft`, changing the customer and verifying the sales total.

- [ ] **Step 2: Write failing tests for deletion and non-draft protection.**

For both order types, assert that deleting a draft removes its row and all item rows while leaving `Product.stock`, `InventoryTransaction`, `AccountPayable`, and `AccountReceivable` unchanged. Parameterize the non-draft statuses and assert `ValueError` with no database mutation:

```python
with pytest.raises(ValueError, match="草稿"):
    update_purchase_order_draft(order, supplier_id, lines)
with pytest.raises(ValueError, match="草稿"):
    delete_purchase_order_draft(order)
```

- [ ] **Step 3: Run the focused tests and verify they fail.**

Run:

```bash
PYTHONPATH=. pytest tests/test_purchase_orders.py tests/test_sales_orders.py -k "update_purchase_order_draft or delete_purchase_order_draft or update_sales_order_draft or delete_sales_order_draft" -q
```

Expected: import or collection failures because the four service functions do not exist yet.

- [ ] **Step 4: Implement service functions with transaction-safe replacement.**

Use `_normalize_lines` to validate all lines before mutating the order. Each update function must reject non-drafts, look up the new supplier/customer, calculate the total from normalized lines, update the party foreign key, remove current item objects, append new item objects, update only `total_amount`, and commit once. Preserve `order_no`, `created_at`, and `status`.

Each delete function must reject non-drafts, call `db.session.delete(order)`, commit once, and rely on the existing `cascade="all, delete-orphan"`. Record success and error operations using the four function-specific action names; rollback and re-raise on `SQLAlchemyError`.

- [ ] **Step 5: Run the service tests and existing order suites.**

Run:

```bash
PYTHONPATH=. pytest tests/test_purchase_orders.py tests/test_sales_orders.py -q
```

Expected: all purchase and sales tests pass, including the new service tests.

- [ ] **Step 6: Commit the service layer.**

```bash
git add services/orders.py tests/test_purchase_orders.py tests/test_sales_orders.py
git commit -m "feat: add draft order update and delete services"
```

### Task 2: Add purchase draft edit/delete routes and UI

**Files:**
- Modify: `routes/purchase_orders.py`
- Modify: `templates/purchase_orders/form.html`
- Modify: `templates/purchase_orders/detail.html`
- Test: `tests/test_purchase_orders.py`

**Interfaces:**
- Consumes: Task 1 `update_purchase_order_draft` and `delete_purchase_order_draft`.
- Produces: `purchase_orders.edit_purchase_order` and `purchase_orders.delete_purchase_order` routes; the existing form template accepts `edit_mode`, `form_action`, `page_title`, `page_description`, `submit_label`, and `cancel_url`.

- [ ] **Step 1: Add failing route and HTML tests.**

Cover GET prefill, POST replacement of supplier and lines, total recalculation, deletion cascade, no inventory/payable changes, draft-only controls, and HTTP 400 protection for pending receipt and completed orders:

```python
def test_purchase_draft_edit_get_prefills_current_values(app, master_data):
    client = app.test_client()
    client.post("/purchase-orders/new", data=purchase_form(
        master_data["supplier_id"],
        [(master_data["keyboard_id"], 2, "80")],
    ))
    with app.app_context():
        order_id = PurchaseOrder.query.one().id
    response = client.get(f"/purchase-orders/{order_id}/edit")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'name="supplier_id"' in html
    assert f'value="{master_data["keyboard_id"]}"' in html
    assert 'value="2"' in html
    assert 'value="80"' in html
    assert "编辑采购订单" in html

def test_purchase_draft_delete_removes_order_and_items(app, master_data):
    client = app.test_client()
    client.post("/purchase-orders/new", data=purchase_form(
        master_data["supplier_id"],
        [(master_data["keyboard_id"], 2, "80")],
    ))
    with app.app_context():
        order_id = PurchaseOrder.query.one().id
    response = client.post(f"/purchase-orders/{order_id}/delete")
    assert response.status_code == 302
    with app.app_context():
        assert PurchaseOrder.query.count() == 0
        assert PurchaseOrderItem.query.count() == 0
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0
```

- [ ] **Step 2: Run purchase route tests to verify they fail.**

```bash
PYTHONPATH=. pytest tests/test_purchase_orders.py -k "draft_edit or draft_delete or edit_purchase_order" -q
```

Expected: missing route or template-context failures before implementation.

- [ ] **Step 3: Refactor purchase form rendering without changing new-order behavior.**

Add an order-to-form helper:

```python
def _form_data_from_order(order):
    return {
        "supplier_id": str(order.supplier_id),
        "selected_product_ids": [str(item.product_id) for item in order.items],
        "quantities": {str(item.product_id): str(item.quantity) for item in order.items},
        "unit_prices": {str(item.product_id): str(item.unit_price) for item in order.items},
    }
```

Parameterize the existing form template with `form_action`, title, description, submit label, and cancel URL. Keep `/new` on the existing draft-creation path.

- [ ] **Step 4: Implement purchase edit and delete routes.**

Add `/<int:order_id>/edit` GET/POST and `/<int:order_id>/delete` POST routes. The edit route rejects non-drafts with HTTP 400, reads the existing form shape, reuses `_validate_form`, calls `update_purchase_order_draft`, and preserves submitted data on validation errors. The delete route rejects non-drafts, calls the service, and redirects to the list.

On the draft detail template, render an edit link and a POST delete form with `onsubmit="return confirm('确定删除这份采购草稿吗？')"`; do not render them for pending or completed orders.

- [ ] **Step 5: Run purchase tests.**

```bash
PYTHONPATH=. pytest tests/test_purchase_orders.py -q
```

Expected: all purchase create, edit, delete, submit, receive, payable, and side-effect tests pass.

- [ ] **Step 6: Commit the purchase implementation.**

```bash
git add routes/purchase_orders.py templates/purchase_orders/form.html templates/purchase_orders/detail.html tests/test_purchase_orders.py
git commit -m "feat: add purchase draft edit and delete UI"
```

### Task 3: Add sales draft edit/delete routes and UI

**Files:**
- Modify: `routes/sales_orders.py`
- Modify: `templates/sales_orders/form.html`
- Modify: `templates/sales_orders/detail.html`
- Test: `tests/test_sales_orders.py`

**Interfaces:**
- Consumes: Task 1 `update_sales_order_draft` and `delete_sales_order_draft`.
- Produces: `sales_orders.edit_sales_order` and `sales_orders.delete_sales_order` routes; the sales form template accepts the same edit-mode parameters with customer-specific copy.

- [ ] **Step 1: Add failing sales route and HTML tests.**

Cover GET prefill, POST replacement of customer and lines, total recalculation, deletion cascade, no stock/receivable/inventory changes, draft-only controls, and HTTP 400 protection for pending shipment and completed orders:

```python
def test_sales_draft_edit_post_updates_order_without_side_effects(app, master_data):
    client = app.test_client()
    client.post("/sales-orders/new", data=sales_form(
        master_data["customer_id"],
        [(master_data["keyboard_id"], 1, "120")],
    ))
    with app.app_context():
        order_id = SalesOrder.query.one().id
        initial_stock = db.session.get(Product, master_data["keyboard_id"]).stock
    response = client.post(
        f"/sales-orders/{order_id}/edit",
        data=sales_form(master_data["customer_id"], [
            (master_data["mouse_id"], 3, "65.50"),
        ]),
    )
    assert response.status_code == 302
    with app.app_context():
        order = db.session.get(SalesOrder, order_id)
        assert order.status == "draft"
        assert order.total_amount == Decimal("196.50")
        assert order.items[0].product_id == master_data["mouse_id"]
        assert db.session.get(Product, master_data["keyboard_id"]).stock == initial_stock
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0

def test_sales_draft_delete_removes_order_and_items(app, master_data):
    client = app.test_client()
    client.post("/sales-orders/new", data=sales_form(
        master_data["customer_id"],
        [(master_data["keyboard_id"], 1, "120")],
    ))
    with app.app_context():
        order_id = SalesOrder.query.one().id
    response = client.post(f"/sales-orders/{order_id}/delete")
    assert response.status_code == 302
    with app.app_context():
        assert SalesOrder.query.count() == 0
        assert SalesOrderItem.query.count() == 0
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0
```

- [ ] **Step 2: Run sales route tests to verify they fail.**

```bash
PYTHONPATH=. pytest tests/test_sales_orders.py -k "draft_edit or draft_delete or edit_sales_order" -q
```

Expected: missing route or template behavior failures before implementation.

- [ ] **Step 3: Parameterize the sales form for new and edit modes.**

Add `_form_data_from_order(order)` using customer id and sales line values. Keep `/new` behavior unchanged, but pass edit-specific title, description, submit label, form action, and cancel link to the shared form template.

- [ ] **Step 4: Implement sales edit and delete routes.**

Add `/<int:order_id>/edit` GET/POST and `/<int:order_id>/delete` POST routes. Enforce `order.status == "draft"` before rendering, validating, or deleting. Use `_validate_form`, call the Task 1 service, preserve submitted data on validation errors, and redirect after success.

Add draft-only edit/delete controls to the sales detail template with a confirmation prompt. Leave submit, shipment, receivable, and inventory branches unchanged.

- [ ] **Step 5: Run sales tests.**

```bash
PYTHONPATH=. pytest tests/test_sales_orders.py -q
```

Expected: all sales create, edit, delete, submit, ship, receivable, and side-effect tests pass.

- [ ] **Step 6: Commit the sales implementation.**

```bash
git add routes/sales_orders.py templates/sales_orders/form.html templates/sales_orders/detail.html tests/test_sales_orders.py
git commit -m "feat: add sales draft edit and delete UI"
```

### Task 4: Cross-workflow regression and documentation verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_ui_layout.py`
- Test: `tests/test_purchase_orders.py`
- Test: `tests/test_sales_orders.py`

**Interfaces:**
- Consumes: Task 2 and Task 3 routes, templates, and service operations.
- Produces: documented draft lifecycle and final regression evidence.

- [ ] **Step 1: Add UI regression assertions.**

Add assertions like these to the existing Flask client tests:

```python
draft_html = client.get(f"/purchase-orders/{draft_id}").get_data(as_text=True)
assert f"/purchase-orders/{draft_id}/edit" in draft_html
assert f"/purchase-orders/{draft_id}/delete" in draft_html
assert "确定删除这份采购草稿吗？" in draft_html

pending_html = client.get(f"/purchase-orders/{pending_id}").get_data(as_text=True)
assert f"/purchase-orders/{pending_id}/edit" not in pending_html
assert f"/purchase-orders/{pending_id}/delete" not in pending_html
```

Repeat the same assertions for sales URLs and the sales confirmation copy. Assert the shared form receives the edit action URL and renders the `编辑采购订单` or `编辑销售订单` title.

- [ ] **Step 2: Add README lifecycle documentation.**

Document that draft purchase and sales orders can be edited or deleted, while submitted, pending, and completed orders are immutable through these routes. State that deletion only removes the draft and its lines and does not affect inventory or financial records.

- [ ] **Step 3: Run focused and complete verification.**

```bash
PYTHONPATH=. pytest tests/test_purchase_orders.py tests/test_sales_orders.py tests/test_ui_layout.py -q
PYTHONPATH=. pytest -q
git diff --check
```

Expected: all focused tests pass, the complete suite has zero failures, and `git diff --check` is clean.

- [ ] **Step 4: Commit documentation and final regression tests.**

```bash
git add README.md tests/test_ui_layout.py tests/test_purchase_orders.py tests/test_sales_orders.py
git commit -m "test: verify draft order lifecycle safeguards"
```

- [ ] **Step 5: Report final verification.**

Report changed files, route behavior, draft-only safeguards, side-effect guarantees, focused test results, full test results, and whether all pre-existing ERP tests remain green.
