# 仓储与库存导航模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将采购入库、销售出库、当前库存和库存流水四个灰色导航项目变为可访问、可操作且有回归测试的 ERP 页面。

**Architecture:** 新增一个 `inventory` Flask blueprint，提供四个只读 GET 页面：两个履约队列页和两个库存查询页。履约队列只查询待处理订单并链接到现有订单详情，实际入库/出库继续使用原有 POST 事务；当前库存和库存流水直接读取现有 `Product` 与 `InventoryTransaction` 数据。共享导航在桌面端和移动端使用同一组 endpoint 高亮规则。

**Tech Stack:** Flask, Flask-SQLAlchemy, Jinja2, Bootstrap 5.3.3, CSS, pytest

## Global Constraints

- 不新增独立的入库单或出库单数据模型。
- 不实现部分入库、部分出库、库存盘点、库存调整、退货、搜索、筛选、分页或导出。
- 不改变订单状态机、库存事务、应收应付、AI 接口、现有表单字段或现有履约 POST action。
- 新页面只读；库存余额只能由现有入库/出库业务修改。
- 队列和流水按记录 ID 倒序；当前库存按商品名称和 ID 稳定排序。
- 空数据页面返回 HTTP 200，并显示明确空状态和可用导航入口。
- 页面沿用现有 `base.html`、`surface-card`、`table-responsive`、`status-pill` 和暖白/珊瑚红视觉系统。
- 每个实现任务先写会失败的测试，再写最小实现；每个任务结束后运行对应测试并提交。

## File Map

- Create: `routes/inventory.py` — 四个 GET 页面、查询顺序、页面状态/类型标签。
- Modify: `app.py` — 注册 `inventory_bp`。
- Create: `templates/inventory/purchase_receipts.html` — 待入库采购订单队列。
- Create: `templates/inventory/sales_shipments.html` — 待出库销售订单队列。
- Create: `templates/inventory/current.html` — 当前库存余额表。
- Create: `templates/inventory/transactions.html` — 入库/出库流水表。
- Modify: `templates/base.html` — 桌面端和移动端四个真实导航链接及当前页高亮。
- Modify: `static/css/style.css` — 队列操作区、库存状态和空状态的最小共享样式。
- Create: `tests/test_inventory_pages.py` — 四个页面的数据和空状态回归测试。
- Modify: `tests/test_ui_layout.py` — 共享壳层页面参数和新导航高亮契约。

---

### Task 1: Lock the new pages and navigation contracts with failing tests

**Files:**
- Create: `tests/test_inventory_pages.py`
- Modify: `tests/test_ui_layout.py`

**Interfaces:**
- Consumes: `create_app(test_config)` from `app.py`, `db` and existing models from `models.py`.
- Produces: tests that define the four URL paths, endpoint names, queue filtering, inventory rendering, transaction labels, empty states, and shared navigation metadata before production routes/templates exist.

- [ ] **Step 1: Create the isolated test fixture and seed helper**

Create a temporary SQLite fixture that calls `db.create_all()` and drops all tables during teardown. Add a helper with this exact shape so every test can build the same realistic records:

```python
def seed_inventory_data(app):
    with app.app_context():
        supplier = Supplier(name="供应商 A", phone="")
        customer = Customer(name="客户 A", phone="")
        keyboard = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=8
        )
        mouse = Product(
            name="鼠标", sku="MS001", purchase_price=40, sale_price=69, stock=0
        )
        db.session.add_all([supplier, customer, keyboard, mouse])
        db.session.flush()
        pending_purchase = PurchaseOrder(
            order_no="PO-PENDING",
            supplier_id=supplier.id,
            status="pending_receipt",
            total_amount=160,
        )
        completed_purchase = PurchaseOrder(
            order_no="PO-COMPLETED",
            supplier_id=supplier.id,
            status="completed",
            total_amount=80,
        )
        pending_sales = SalesOrder(
            order_no="SO-PENDING",
            customer_id=customer.id,
            status="pending_shipment",
            total_amount=240,
        )
        completed_sales = SalesOrder(
            order_no="SO-COMPLETED",
            customer_id=customer.id,
            status="completed",
            total_amount=120,
        )
        db.session.add_all(
            [pending_purchase, completed_purchase, pending_sales, completed_sales]
        )
        db.session.flush()
        db.session.add_all(
            [
                PurchaseOrderItem(
                    purchase_order=pending_purchase,
                    product_id=keyboard.id,
                    quantity=2,
                    unit_price=80,
                ),
                SalesOrderItem(
                    sales_order=pending_sales,
                    product_id=keyboard.id,
                    quantity=2,
                    unit_price=120,
                ),
                InventoryTransaction(
                    product_id=keyboard.id,
                    type="inbound",
                    quantity=10,
                    related_order_no="PO-COMPLETED",
                    balance_after=8,
                ),
                InventoryTransaction(
                    product_id=keyboard.id,
                    type="outbound",
                    quantity=2,
                    related_order_no="SO-COMPLETED",
                    balance_after=8,
                ),
            ]
        )
        db.session.commit()
        return {
            "pending_purchase_id": pending_purchase.id,
            "pending_sales_id": pending_sales.id,
        }
```

Import `Customer`, `InventoryTransaction`, `Product`, `PurchaseOrder`, `PurchaseOrderItem`, `SalesOrder`, `SalesOrderItem`, `Supplier`, and `db` at the top of the test module.

- [ ] **Step 2: Add failing availability and empty-state tests**

Add this parameterized test to define the new endpoint contract:

```python
@pytest.mark.parametrize(
    "path,endpoint,title,empty_text",
    [
        ("/purchase-receipts", "inventory.purchase_receipts", "采购入库", "暂无待入库采购订单"),
        ("/sales-shipments", "inventory.sales_shipments", "销售出库", "暂无待出库销售订单"),
        ("/inventory", "inventory.current_inventory", "当前库存", "暂无商品库存数据"),
        ("/inventory/transactions", "inventory.inventory_transactions", "库存流水", "暂无库存流水记录"),
    ],
)
def test_inventory_pages_render_empty_states(app, path, endpoint, title, empty_text):
    response = app.test_client().get(path)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'data-page="{endpoint}"' in body
    assert title in body
    assert empty_text in body
```

- [ ] **Step 3: Add failing queue, inventory, and transaction behavior tests**

Add tests that seed data and assert real rendered content, not only template class names:

```python
def test_purchase_receipts_only_show_pending_orders_and_link_to_detail(app):
    ids = seed_inventory_data(app)
    body = app.test_client().get("/purchase-receipts").get_data(as_text=True)

    assert "PO-PENDING" in body
    assert "PO-COMPLETED" not in body
    assert f'/purchase-orders/{ids["pending_purchase_id"]}' in body


def test_sales_shipments_only_show_pending_orders_and_link_to_detail(app):
    ids = seed_inventory_data(app)
    body = app.test_client().get("/sales-shipments").get_data(as_text=True)

    assert "SO-PENDING" in body
    assert "SO-COMPLETED" not in body
    assert f'/sales-orders/{ids["pending_sales_id"]}' in body


def test_current_inventory_shows_stock_and_status_for_each_product(app):
    seed_inventory_data(app)
    body = app.test_client().get("/inventory").get_data(as_text=True)

    assert "机械键盘" in body
    assert "KB001" in body
    assert "8" in body
    assert "有库存" in body
    assert "鼠标" in body
    assert "暂无库存" in body


def test_inventory_transactions_show_type_quantity_balance_and_order(app):
    seed_inventory_data(app)
    body = app.test_client().get("/inventory/transactions").get_data(as_text=True)

    assert "入库" in body
    assert "出库" in body
    assert "PO-COMPLETED" in body
    assert "SO-COMPLETED" in body
    assert "变更后库存" in body
```

- [ ] **Step 4: Extend the shared-shell route list and active navigation test**

Append these paths to the existing `test_primary_pages_render_the_shared_shell` parameter list in `tests/test_ui_layout.py`:

```python
("/purchase-receipts", "inventory.purchase_receipts"),
("/sales-shipments", "inventory.sales_shipments"),
("/inventory", "inventory.current_inventory"),
("/inventory/transactions", "inventory.inventory_transactions"),
```

Add this parameterized active-link assertion. The existing `ActiveNavTags` parser intentionally counts the desktop and mobile active links as two matches:

```python
@pytest.mark.parametrize(
    "path,nav_endpoint,href",
    [
        ("/purchase-receipts", "inventory.purchase_receipts", "/purchase-receipts"),
        ("/sales-shipments", "inventory.sales_shipments", "/sales-shipments"),
        ("/inventory", "inventory.current_inventory", "/inventory"),
        ("/inventory/transactions", "inventory.inventory_transactions", "/inventory/transactions"),
    ],
)
def test_inventory_page_is_active_in_desktop_and_mobile_navigation(
    app, path, nav_endpoint, href
):
    body = app.test_client().get(path).get_data(as_text=True)
    parser = ActiveNavTags()
    parser.feed(body)

    assert len(parser.active_links) == 2
    assert all(link["href"] == href for link in parser.active_links)
    assert all(link["data-nav-endpoint"] == nav_endpoint for link in parser.active_links)
```

- [ ] **Step 5: Run the focused tests and verify the red state**

Run:

```bash
pytest -q tests/test_inventory_pages.py tests/test_ui_layout.py
```

Expected: the new tests fail with 404 responses or missing endpoint/template output because `inventory_bp` and the four templates do not exist yet. Existing tests unrelated to the new pages should still collect successfully; fix only test syntax or fixture errors before implementing production code.

- [ ] **Step 6: Commit the red tests**

```bash
git add tests/test_inventory_pages.py tests/test_ui_layout.py
git commit -m "test: define warehouse inventory page contracts"
```

### Task 2: Add the read-only inventory blueprint and register it

**Files:**
- Create: `routes/inventory.py`
- Modify: `app.py`
- Test: `tests/test_inventory_pages.py`

**Interfaces:**
- Consumes: `PurchaseOrder`, `SalesOrder`, `Product`, `InventoryTransaction`, `db`, and `render_template`.
- Produces: `inventory.purchase_receipts`, `inventory.sales_shipments`, `inventory.current_inventory`, and `inventory.inventory_transactions` GET endpoints.

- [ ] **Step 1: Implement the minimal blueprint queries**

Create the blueprint with these exact route behaviors:

```python
from flask import Blueprint, render_template

from models import InventoryTransaction, Product, PurchaseOrder, SalesOrder


inventory_bp = Blueprint("inventory", __name__)

PURCHASE_RECEIPT_STATUS_LABELS = {"pending_receipt": "待入库"}
SALES_SHIPMENT_STATUS_LABELS = {"pending_shipment": "待出库"}
INVENTORY_TRANSACTION_TYPE_LABELS = {"inbound": "入库", "outbound": "出库"}


@inventory_bp.get("/purchase-receipts")
def purchase_receipts():
    orders = PurchaseOrder.query.filter_by(status="pending_receipt").order_by(
        PurchaseOrder.id.desc()
    ).all()
    return render_template(
        "inventory/purchase_receipts.html",
        orders=orders,
        status_labels=PURCHASE_RECEIPT_STATUS_LABELS,
    )


@inventory_bp.get("/sales-shipments")
def sales_shipments():
    orders = SalesOrder.query.filter_by(status="pending_shipment").order_by(
        SalesOrder.id.desc()
    ).all()
    return render_template(
        "inventory/sales_shipments.html",
        orders=orders,
        status_labels=SALES_SHIPMENT_STATUS_LABELS,
    )


@inventory_bp.get("/inventory")
def current_inventory():
    products = Product.query.order_by(Product.name, Product.id).all()
    return render_template("inventory/current.html", products=products)


@inventory_bp.get("/inventory/transactions")
def inventory_transactions():
    transactions = InventoryTransaction.query.order_by(
        InventoryTransaction.id.desc()
    ).all()
    return render_template(
        "inventory/transactions.html",
        transactions=transactions,
        type_labels=INVENTORY_TRANSACTION_TYPE_LABELS,
    )
```

Do not add POST routes, request parameters, direct stock writes, or new service functions.

- [ ] **Step 2: Register the blueprint in the application factory**

In `app.py`, import `inventory_bp` next to the other route blueprints and register it after the existing business blueprints:

```python
from routes.inventory import inventory_bp

# inside create_app
app.register_blueprint(inventory_bp)
```

The route registration must happen before `create_app()` returns so the endpoint names in the tests resolve.

- [ ] **Step 3: Run the focused tests and make the route layer green**

Run:

```bash
pytest -q tests/test_inventory_pages.py tests/test_ui_layout.py
```

Expected: route tests now reach Jinja rendering but fail only because the four templates and their navigation links are not present. If a query test fails, verify the status filter and `id.desc()` ordering rather than changing the test fixture.

- [ ] **Step 4: Commit the route layer**

```bash
git add routes/inventory.py app.py
git commit -m "feat: add warehouse inventory read pages"
```

### Task 3: Add the four page templates and data presentations

**Files:**
- Create: `templates/inventory/purchase_receipts.html`
- Create: `templates/inventory/sales_shipments.html`
- Create: `templates/inventory/current.html`
- Create: `templates/inventory/transactions.html`
- Test: `tests/test_inventory_pages.py`

**Interfaces:**
- Consumes: route context variables `orders`, `products`, `transactions`, `status_labels`, and `type_labels`.
- Produces: semantic `data-page-type` markers, responsive tables, real links to existing order detail pages, readable empty states, and cross-navigation among the four modules.

- [ ] **Step 1: Create the purchase receipt queue template**

Extend `base.html`, set the title to `采购入库 - ERP Demo`, and render a `data-page-type="inventory-queue"` page. The table must include `订单号`, `供应商`, `创建时间`, `状态`, `总金额`, and `操作`. For each order, use:

```jinja2
<a class="btn btn-outline-secondary btn-sm" href="{{ url_for('purchase_orders.purchase_order_detail', order_id=order.id) }}">处理入库</a>
```

Render `暂无待入库采购订单` in the empty row. Add header actions linking to `purchase_orders.list_purchase_orders` and `purchase_orders.new_purchase_order`.

- [ ] **Step 2: Create the sales shipment queue template**

Use the same table/card structure with `data-page-type="inventory-queue"`, title `销售出库 - ERP Demo`, and columns `订单号`, `客户`, `创建时间`, `状态`, `总金额`, and `操作`. Use:

```jinja2
<a class="btn btn-outline-secondary btn-sm" href="{{ url_for('sales_orders.sales_order_detail', order_id=order.id) }}">处理出库</a>
```

Render `暂无待出库销售订单` for an empty queue. Add header actions linking to the sales order list and new sales order page.

- [ ] **Step 3: Create the current inventory template**

Use `data-page-type="inventory-list"` and a responsive `surface-card table-card`. Show `商品`, `SKU`, `当前库存`, and `库存状态`. For each product render:

```jinja2
<span class="inventory-stock-value">{{ product.stock }}</span>
{% if product.stock > 0 %}
  <span class="status-pill status-pill--success">有库存</span>
{% else %}
  <span class="status-pill status-pill--info">暂无库存</span>
{% endif %}
```

Render `暂无商品库存数据` when there are no products. Include links to `inventory.inventory_transactions`, `inventory.purchase_receipts`, and `inventory.sales_shipments`; do not include an edit-stock form.

- [ ] **Step 4: Create the inventory transaction template**

Use `data-page-type="inventory-list"` and a responsive table with `商品`, `SKU`, `类型`, `数量`, `变更后库存`, `关联订单`, and `时间`. Render the type through `type_labels[transaction.type]` and use `status-pill--success` for inbound and `status-pill--info` for outbound. Render `暂无库存流水记录` when empty and include links to the current inventory and both queue pages.

- [ ] **Step 5: Run focused tests and verify all data contracts**

Run:

```bash
pytest -q tests/test_inventory_pages.py tests/test_ui_layout.py
```

Expected: all new page, queue filtering, inventory, transaction, empty-state, and shared-shell tests pass. The test output must not include template errors or warnings.

- [ ] **Step 6: Commit the templates**

```bash
git add templates/inventory
git commit -m "feat: render warehouse and inventory pages"
```

### Task 4: Replace disabled navigation items and add responsive styles

**Files:**
- Modify: `templates/base.html`
- Modify: `static/css/style.css`
- Test: `tests/test_inventory_pages.py`, `tests/test_ui_layout.py`

**Interfaces:**
- Consumes: the four `inventory.*` endpoints and existing `request.endpoint` checks.
- Produces: working desktop/mobile navigation with exactly two active links per new page (desktop and mobile), keyboard-visible focus, and readable queue/inventory controls on narrow screens.

- [ ] **Step 1: Replace the four desktop disabled anchors**

Replace the disabled `href="#"` entries in `base.html` with these endpoint contracts:

```jinja2
<a class="nav-link {% if request.endpoint == 'inventory.purchase_receipts' %}active{% endif %}"
   data-nav-endpoint="inventory.purchase_receipts"
   {% if request.endpoint == 'inventory.purchase_receipts' %}aria-current="page"{% endif %}
   href="{{ url_for('inventory.purchase_receipts') }}">采购入库</a>
<a class="nav-link {% if request.endpoint == 'inventory.sales_shipments' %}active{% endif %}"
   data-nav-endpoint="inventory.sales_shipments"
   {% if request.endpoint == 'inventory.sales_shipments' %}aria-current="page"{% endif %}
   href="{{ url_for('inventory.sales_shipments') }}">销售出库</a>
<a class="nav-link {% if request.endpoint == 'inventory.current_inventory' %}active{% endif %}"
   data-nav-endpoint="inventory.current_inventory"
   {% if request.endpoint == 'inventory.current_inventory' %}aria-current="page"{% endif %}
   href="{{ url_for('inventory.current_inventory') }}">当前库存</a>
<a class="nav-link {% if request.endpoint == 'inventory.inventory_transactions' %}active{% endif %}"
   data-nav-endpoint="inventory.inventory_transactions"
   {% if request.endpoint == 'inventory.inventory_transactions' %}aria-current="page"{% endif %}
   href="{{ url_for('inventory.inventory_transactions') }}">库存流水</a>
```

Keep the existing group labels and existing working links unchanged.

- [ ] **Step 2: Add the same four links to mobile navigation**

Add the four `mobile-nav-link` anchors inside `.mobile-nav-panel`. Each uses the matching `url_for`, `request.endpoint` active class, and `aria-current="page"`. Keep the mobile links in the same business/inventory order as the desktop links.

- [ ] **Step 3: Add minimal page-specific style hooks**

Append styles to `static/css/style.css` without changing the existing token values or responsive table contract:

```css
.inventory-toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.inventory-stock-value { display: inline-block; min-width: 3rem; font-weight: 800; }
.inventory-empty { margin: 0; padding: 2.5rem 1rem; text-align: center; }
@media (max-width: 560px) {
  .inventory-toolbar { align-items: stretch; flex-direction: column; }
  .inventory-toolbar .btn { width: 100%; }
}
```

Use `.inventory-toolbar` around page header action groups and `.inventory-empty` on all four empty-state paragraphs/rows where the element supports it. Do not make tables narrower than the existing `680px` minimum.

- [ ] **Step 4: Run navigation and focused page tests**

Run:

```bash
pytest -q tests/test_inventory_pages.py tests/test_ui_layout.py
```

Expected: all focused tests pass, including `data-nav-endpoint`, `aria-current`, desktop/mobile active-link count, and the existing CSS accessibility/overflow assertions.

- [ ] **Step 5: Commit the navigation and styles**

```bash
git add templates/base.html static/css/style.css tests/test_inventory_pages.py tests/test_ui_layout.py
git commit -m "feat: enable warehouse inventory navigation"
```

### Task 5: Run full verification and inspect rendered pages

**Files:**
- Modify only if verification exposes a concrete defect: the files from Tasks 2–4.
- Test: all existing test files through the repository test command.

**Interfaces:**
- Consumes: the completed routes, templates, navigation, and existing order fulfillment behavior.
- Produces: evidence that the new pages do not regress order receipt/shipment, settlements, AI, logs, dashboard, or existing responsive UI contracts.

- [ ] **Step 1: Run the full automated suite**

Run:

```bash
pytest -q
```

Expected: all tests pass. If a test fails, identify whether the failure is caused by the new route registration, template output, navigation count, or unrelated pre-existing state before editing anything.

- [ ] **Step 2: Verify the endpoint map and method safety**

Run:

```bash
python -c 'from app import create_app; app = create_app({"TESTING": True}); print(sorted((rule.rule, sorted(rule.methods - {"HEAD", "OPTIONS"}), rule.endpoint) for rule in app.url_map.iter_rules() if rule.endpoint.startswith("inventory.")))'
```

Expected output contains exactly four GET routes:

```text
('/inventory', ['GET'], 'inventory.current_inventory')
('/inventory/transactions', ['GET'], 'inventory.inventory_transactions')
('/purchase-receipts', ['GET'], 'inventory.purchase_receipts')
('/sales-shipments', ['GET'], 'inventory.sales_shipments')
```

- [ ] **Step 3: Render representative pages for visual inspection**

Start the app with the repository’s documented command, then inspect `/purchase-receipts`, `/sales-shipments`, `/inventory`, `/inventory/transactions`, and one existing pending order detail page at desktop and narrow widths. Confirm that queue actions are readable, tables scroll horizontally instead of overlapping, empty states remain visible, and the current navigation item is highlighted in both desktop and mobile navigation.

- [ ] **Step 4: Review the final diff and status**

Run:

```bash
git diff HEAD~4..HEAD --stat
git status --short
```

Confirm the diff contains only the approved route, template, navigation, CSS, and test changes. Preserve the pre-existing untracked `docs/superpowers/plans/2026-09-21-replenishment-analysis.md` file.

- [ ] **Step 5: Commit any verified correction**

If visual or full-suite verification required a correction, rerun the affected focused test and then commit only the correction:

```bash
git add routes/inventory.py app.py templates/inventory templates/base.html static/css/style.css tests/test_inventory_pages.py tests/test_ui_layout.py
git commit -m "fix: polish warehouse inventory pages"
```

Do not claim completion until the full `pytest -q` result is green and the rendered-page inspection is complete.
