# 类小红书 ERP 全站外观改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 Flask ERP 业务接口的前提下，将所有页面统一为浅色、卡片化、留白充足且接近用户参考图节奏的视觉系统。

**Architecture:** 保留现有 Flask/Jinja2/Bootstrap 5 结构，先用模板回归测试锁定共享壳层和关键 DOM 契约，再重构 `base.html` 与单个全局 CSS；业务页面按首页、基础资料、订单/财务/日志、AI 助手分批迁移到语义化布局。当前 endpoint 由 Jinja 的 `request.endpoint` 决定导航高亮，现有 POST action、表单字段和 AI 请求协议全部不变。

**Tech Stack:** Flask, Jinja2, Bootstrap 5.3.3, CSS media queries, 原生 HTML `details`, pytest

## Global Constraints

- 不修改 `app.py`、`models.py`、`routes/`、`services/`、`agent/` 中的业务逻辑或数据接口。
- 不改变现有表单字段 `name`、POST action、AI 请求路径、请求体或确认 token 流程。
- 不引入新的前端框架、图标包或未被请求的后端搜索/筛选功能。
- 主色使用珊瑚红，页面保持暖白/浅灰背景、白色圆角卡片、低透明度阴影。
- 所有页面必须在桌面端和窄屏端可读；表格使用横向滚动，不压缩关键数据。
- 每个实现任务都先写一个会失败的回归测试，再实现最小改动使其通过。

---

### Task 1: 建立共享壳层和页面类型的回归测试

**Files:**
- Create: `tests/test_ui_layout.py`

**Interfaces:**
- Consumes: `create_app(test_config)` from `app.py`, `db` from `models.py`.
- Produces: 可重复执行的模板回归检查，要求主页面包含 `data-app-shell="erp"` 和当前 endpoint 的 `data-page`；后续任务再分别锁定页面类型和视觉容器。

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

import pytest

from app import create_app
from models import db


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'ui.db'}",
        }
    )
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize(
    "path,endpoint",
    [
        ("/", "dashboard"),
        ("/assistant", "assistant.assistant_page"),
        ("/products", "products.list_products"),
        ("/products/new", "products.new_product"),
        ("/customers", "customers.list_customers"),
        ("/suppliers", "suppliers.list_suppliers"),
        ("/purchase-orders", "purchase_orders.list_purchase_orders"),
        ("/purchase-orders/new", "purchase_orders.new_purchase_order"),
        ("/sales-orders", "sales_orders.list_sales_orders"),
        ("/sales-orders/new", "sales_orders.new_sales_order"),
        ("/receivables", "settlements.list_receivables"),
        ("/payables", "settlements.list_payables"),
        ("/logs/database", "logs.database_logs"),
        ("/logs/api", "logs.api_logs"),
    ],
)
def test_primary_pages_render_the_shared_shell(app, path, endpoint):
    response = app.test_client().get(path)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-app-shell="erp"' in body
    assert f'data-page="{endpoint}"' in body


def test_current_page_is_the_only_active_navigation_link(app):
    response = app.test_client().get("/products")
    body = response.get_data(as_text=True)

    assert 'href="/products"' in body
    assert 'data-nav-endpoint="products.list_products"' in body
    assert 'aria-current="page"' in body


def test_dashboard_keeps_all_existing_metric_values(app):
    response = app.test_client().get("/")
    body = response.get_data(as_text=True)

    assert "商品数量" in body
    assert "当前总库存" in body
    assert "未收应收账款" in body
    assert "销售总额（已完成出库）" in body


def test_assistant_keeps_the_javascript_contract(app):
    response = app.test_client().get("/assistant")
    body = response.get_data(as_text=True)

    assert 'id="assistant-chat"' in body
    assert 'id="assistant-form"' in body
    assert 'id="assistant-input"' in body
    assert 'assistant.js' in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_ui_layout.py`

Expected: FAIL because the current templates do not emit `data-app-shell`, `data-page`, or endpoint metadata. The existing assistant IDs and script include may already pass their compatibility assertions; the new shell assertions are the intended red state.

- [ ] **Step 3: Confirm the failure is structural, not a fixture error**

Run: `pytest -q tests/test_ui_layout.py -x`

Expected: The first response is HTTP 200 and the assertion fails on a missing shared-shell marker. If the response is not HTTP 200, fix only the test fixture or route path before continuing; do not change production templates yet.

- [ ] **Step 4: Keep the test file as the cross-page contract**

Do not add mocks or route-specific business setup. The fixture only creates an empty schema, so later template changes must continue to render empty states correctly.

### Task 2: Rebuild the shared shell and responsive visual system

**Files:**
- Modify: `templates/base.html`
- Modify: `static/css/style.css`

**Interfaces:**
- Consumes: `request.endpoint`, existing Flask `url_for` endpoints, Bootstrap 5 utility classes.
- Produces: `data-app-shell="erp"`, `data-page="{{ request.endpoint }}"`, `data-nav-endpoint` metadata, one active navigation link, `page-header`, `surface-card`, responsive sidebar/details navigation, and CSS tokens used by every page.

- [ ] **Step 1: Add the shared shell markup**

Wrap the document body with a semantic app shell and put the request endpoint on the root element:

```jinja2
<body class="app-body">
  <div class="app-shell" data-app-shell="erp" data-page="{{ request.endpoint }}">
    <aside class="sidebar" aria-label="主导航">
      <a class="brand-mark" href="{{ url_for('dashboard') }}">ERP Demo</a>
      <nav class="sidebar-nav">
        <a class="nav-link {% if request.endpoint == 'dashboard' %}active{% endif %}"
           data-nav-endpoint="dashboard"
           {% if request.endpoint == 'dashboard' %}aria-current="page"{% endif %}
           href="{{ url_for('dashboard') }}">工作台</a>
        <a class="nav-link {% if request.endpoint == 'assistant.assistant_page' %}active{% endif %}"
           data-nav-endpoint="assistant.assistant_page"
           {% if request.endpoint == 'assistant.assistant_page' %}aria-current="page"{% endif %}
           href="{{ url_for('assistant.assistant_page') }}">AI 助手</a>
        <div class="nav-section">基础资料</div>
        <a class="nav-link {% if request.endpoint and request.endpoint.startswith('products.') %}active{% endif %}"
           data-nav-endpoint="products.list_products"
           href="{{ url_for('products.list_products') }}">商品管理</a>
        <a class="nav-link {% if request.endpoint and request.endpoint.startswith('suppliers.') %}active{% endif %}"
           data-nav-endpoint="suppliers.list_suppliers"
           href="{{ url_for('suppliers.list_suppliers') }}">供应商管理</a>
        <a class="nav-link {% if request.endpoint and request.endpoint.startswith('customers.') %}active{% endif %}"
           data-nav-endpoint="customers.list_customers"
           href="{{ url_for('customers.list_customers') }}">客户管理</a>
        <div class="nav-section">业务管理</div>
        <a class="nav-link {% if request.endpoint and request.endpoint.startswith('purchase_orders.') %}active{% endif %}"
           data-nav-endpoint="purchase_orders.list_purchase_orders"
           href="{{ url_for('purchase_orders.list_purchase_orders') }}">采购订单</a>
        <a class="nav-link {% if request.endpoint and request.endpoint.startswith('sales_orders.') %}active{% endif %}"
           data-nav-endpoint="sales_orders.list_sales_orders"
           href="{{ url_for('sales_orders.list_sales_orders') }}">销售订单</a>
        <div class="nav-section">财务与系统</div>
        <a class="nav-link {% if request.endpoint == 'settlements.list_receivables' %}active{% endif %}"
           data-nav-endpoint="settlements.list_receivables"
           href="{{ url_for('settlements.list_receivables') }}">应收账款</a>
        <a class="nav-link {% if request.endpoint == 'settlements.list_payables' %}active{% endif %}"
           data-nav-endpoint="settlements.list_payables"
           href="{{ url_for('settlements.list_payables') }}">应付账款</a>
        <a class="nav-link {% if request.endpoint == 'logs.database_logs' %}active{% endif %}"
           data-nav-endpoint="logs.database_logs"
           href="{{ url_for('logs.database_logs') }}">操作日志</a>
        <a class="nav-link {% if request.endpoint == 'logs.api_logs' %}active{% endif %}"
           data-nav-endpoint="logs.api_logs"
           href="{{ url_for('logs.api_logs') }}">API 日志</a>
      </nav>
    </aside>
    <main class="main-content">
      <details class="mobile-nav">
        <summary>打开导航</summary>
        <nav class="mobile-nav-panel" aria-label="移动端主导航">
          <a class="mobile-nav-link" href="{{ url_for('dashboard') }}">工作台</a>
          <a class="mobile-nav-link" href="{{ url_for('assistant.assistant_page') }}">AI 助手</a>
          <a class="mobile-nav-link" href="{{ url_for('products.list_products') }}">商品管理</a>
          <a class="mobile-nav-link" href="{{ url_for('suppliers.list_suppliers') }}">供应商管理</a>
          <a class="mobile-nav-link" href="{{ url_for('customers.list_customers') }}">客户管理</a>
          <a class="mobile-nav-link" href="{{ url_for('purchase_orders.list_purchase_orders') }}">采购订单</a>
          <a class="mobile-nav-link" href="{{ url_for('sales_orders.list_sales_orders') }}">销售订单</a>
          <a class="mobile-nav-link" href="{{ url_for('settlements.list_receivables') }}">应收账款</a>
          <a class="mobile-nav-link" href="{{ url_for('settlements.list_payables') }}">应付账款</a>
          <a class="mobile-nav-link" href="{{ url_for('logs.database_logs') }}">操作日志</a>
          <a class="mobile-nav-link" href="{{ url_for('logs.api_logs') }}">API 日志</a>
        </nav>
      </details>
      <header class="topbar">
        <span class="topbar-kicker">ERP Demo</span>
        <div class="topbar-actions">
          <a class="btn btn-sm btn-outline-primary" href="{{ url_for('assistant.assistant_page') }}">AI 助手</a>
          <a class="btn btn-sm btn-primary" href="{{ url_for('purchase_orders.new_purchase_order') }}">新建采购订单</a>
          <a class="btn btn-sm btn-primary" href="{{ url_for('sales_orders.new_sales_order') }}">新建销售订单</a>
        </div>
      </header>
      <div class="content-wrap">{% block content %}{% endblock %}</div>
    </main>
  </div>
</body>
```

Use real Jinja markup for the mobile links shown above. Add `aria-current="page"` to the matching mobile link using the same `request.endpoint` checks as the desktop navigation. Preserve the existing disabled placeholder links for inventory receipt, current inventory, inventory history, and sales shipment in the desktop navigation, even though they do not have active endpoints.

- [ ] **Step 2: Add the visual tokens and shell CSS**

Replace the dark fixed sidebar rules with tokens and semantic classes. The minimum contract is:

```css
:root {
  --erp-canvas: #f7f7f5;
  --erp-surface: #ffffff;
  --erp-text: #252525;
  --erp-muted: #7d7d7d;
  --erp-border: #ecece8;
  --erp-primary: #ff385c;
  --erp-primary-soft: #fff0f2;
  --erp-success: #29956a;
  --erp-shadow: 0 12px 32px rgba(38, 38, 38, 0.06);
}

.app-shell { min-height: 100vh; display: grid; grid-template-columns: 232px minmax(0, 1fr); }
.app-body { margin: 0; color: var(--erp-text); background: var(--erp-canvas); }
.sidebar { position: sticky; top: 0; height: 100vh; padding: 24px 14px; background: var(--erp-surface); border-right: 1px solid var(--erp-border); }
.nav-link.active { color: var(--erp-primary); background: var(--erp-primary-soft); }
.main-content { min-width: 0; }
.topbar, .content-wrap { width: min(1440px, 100%); margin: 0 auto; padding-inline: clamp(18px, 3vw, 42px); }
.content-wrap { padding-top: 12px; padding-bottom: 48px; }
.surface-card { border: 1px solid var(--erp-border); border-radius: 20px; background: var(--erp-surface); box-shadow: var(--erp-shadow); }
.page-header { display: flex; justify-content: space-between; gap: 20px; align-items: flex-end; margin-bottom: 24px; }
```

Add focus styles, button overrides, table spacing, and the `@media (max-width: 900px)` rule that switches the grid to one column, hides the desktop sidebar, and shows the native `details.mobile-nav`.

- [ ] **Step 3: Run the shared-shell tests**

Run: `pytest -q tests/test_ui_layout.py`

Expected: The test passes for the shared shell markers and navigation metadata, while page-specific tests may still fail until Tasks 3–5 add `page-header` to every template.

- [ ] **Step 4: Refactor only duplicated shell rules after green**

Keep the CSS organized in this order: tokens/reset, shell, navigation/topbar, page primitives, table/form/status primitives, assistant styles, responsive overrides. Run `pytest -q tests/test_ui_layout.py` again after cleanup.

### Task 3: Redesign the dashboard and master-data pages

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `templates/products/list.html`
- Modify: `templates/products/form.html`
- Modify: `templates/customers/list.html`
- Modify: `templates/customers/form.html`
- Modify: `templates/suppliers/list.html`
- Modify: `templates/suppliers/form.html`
- Modify: `static/css/style.css`

**Interfaces:**
- Consumes: Existing `metrics`, `products`, `customers`, `suppliers`, `form_data`, and `errors` template variables.
- Produces: `page-header` on every page, `surface-card` containers, consistent empty/error states, and no change to form field names or list/edit URLs.

- [ ] **Step 1: Extend the failing page regression assertions**

Add this test to `tests/test_ui_layout.py` before changing the templates:

```python
@pytest.mark.parametrize(
    "path,marker",
    [
        ("/", 'data-page-type="dashboard"'),
        ("/products", 'data-page-type="master-list"'),
        ("/products/new", 'data-page-type="master-form"'),
        ("/customers", 'data-page-type="master-list"'),
        ("/customers/new", 'data-page-type="master-form"'),
        ("/suppliers", 'data-page-type="master-list"'),
        ("/suppliers/new", 'data-page-type="master-form"'),
    ],
)
def test_dashboard_and_master_data_pages_use_page_types(app, path, marker):
    body = app.test_client().get(path).get_data(as_text=True)

    assert marker in body
    assert 'class="surface-card' in body
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `pytest -q tests/test_ui_layout.py -k "dashboard or master_data"`

Expected: FAIL because these templates currently use generic `container-fluid`/`card` markup without `data-page-type` and `surface-card`.

- [ ] **Step 3: Implement the dashboard structure**

Use the existing seven metrics and no fabricated values:

```jinja2
<section class="page-header" data-page-type="dashboard">
  <div>
    <p class="eyebrow">ERP WORKSPACE</p>
    <h1>工作台</h1>
    <p class="page-description">查看当前 ERP 演示数据概况。</p>
  </div>
  <a class="btn btn-primary" href="{{ url_for('assistant.assistant_page') }}">问问 AI 助手</a>
</section>
<section class="metric-grid metric-grid-primary" aria-label="运营指标">
  <article class="surface-card metric-card metric-card--coral"><div class="metric-label">商品数量</div><div class="metric-value">{{ metrics.product_count }}</div></article>
  <article class="surface-card metric-card metric-card--mint"><div class="metric-label">当前总库存</div><div class="metric-value">{{ metrics.total_stock }}</div></article>
  <article class="surface-card metric-card metric-card--lavender"><div class="metric-label">待入库采购订单</div><div class="metric-value">{{ metrics.pending_purchase_count }}</div></article>
  <article class="surface-card metric-card metric-card--peach"><div class="metric-label">待出库销售订单</div><div class="metric-value">{{ metrics.pending_sales_count }}</div></article>
</section>
<section class="metric-grid metric-grid-finance" aria-label="财务与销售指标">
  <article class="surface-card metric-card metric-card--peach"><div class="metric-label">未收应收账款</div><div class="metric-value">¥ {{ "%.2f"|format(metrics.unpaid_receivable) }}</div></article>
  <article class="surface-card metric-card metric-card--mint"><div class="metric-label">未付应付账款</div><div class="metric-value">¥ {{ "%.2f"|format(metrics.unpaid_payable) }}</div></article>
  <article class="surface-card metric-card metric-card--coral"><div class="metric-label">销售总额（已完成出库）</div><div class="metric-value">¥ {{ "%.2f"|format(metrics.sales_total) }}</div></article>
</section>
```

Each metric card must keep its original label and Jinja value expression. Use accent modifier classes such as `metric-card--coral`, `metric-card--mint`, and `metric-card--lavender` only for visual grouping.

- [ ] **Step 4: Implement master-data list and form layouts**

For each list, use a real page header and a single surface card around the existing table. For each form, use a `form-layout` surface card and preserve the current `<form method="post">`, `name` attributes, values, error loop, and cancel URL. The product form keeps the two price inputs in a responsive two-column row; customer and supplier forms keep name/phone fields.

Use this list skeleton for all three master-data pages:

```jinja2
<section class="page-header" data-page-type="master-list">
  <div><p class="eyebrow">MASTER DATA</p><h1>商品管理</h1><p class="page-description">维护商品主数据，库存只能通过库存业务变化。</p></div>
  <a class="btn btn-primary" href="{{ url_for('products.new_product') }}">新增商品</a>
</section>
<section class="surface-card table-card">
  <div class="table-responsive">
    <!-- keep the existing table headings, values, edit URL, and empty row -->
  </div>
</section>
```

- [ ] **Step 5: Run the page regression tests**

Run: `pytest -q tests/test_ui_layout.py -k "dashboard or master_data"`

Expected: PASS with all dashboard/master-data markers present and all current GET routes still returning 200.

- [ ] **Step 6: Run the existing master-data behavior tests**

Run: `pytest -q tests/test_master_data.py tests/test_skeleton.py`

Expected: PASS; no form submission or model behavior should change.

### Task 4: Redesign orders, settlements, and logs without changing workflows

**Files:**
- Modify: `templates/purchase_orders/list.html`
- Modify: `templates/purchase_orders/form.html`
- Modify: `templates/purchase_orders/detail.html`
- Modify: `templates/sales_orders/list.html`
- Modify: `templates/sales_orders/form.html`
- Modify: `templates/sales_orders/detail.html`
- Modify: `templates/receivables/list.html`
- Modify: `templates/payables/list.html`
- Modify: `templates/logs/database.html`
- Modify: `templates/logs/api.html`
- Modify: `static/css/style.css`

**Interfaces:**
- Consumes: Existing order, settlement, log, status label, and inventory transaction variables.
- Produces: `data-page-type="order-list|order-form|order-detail|settlement-list|log-list"`, status pill modifiers, grouped cards, and unchanged POST actions.

- [ ] **Step 1: Add failing markers for business page types**

Add this test to `tests/test_ui_layout.py`:

```python
@pytest.mark.parametrize(
    "path,marker",
    [
        ("/purchase-orders", 'data-page-type="order-list"'),
        ("/purchase-orders/new", 'data-page-type="order-form"'),
        ("/sales-orders", 'data-page-type="order-list"'),
        ("/sales-orders/new", 'data-page-type="order-form"'),
        ("/receivables", 'data-page-type="settlement-list"'),
        ("/payables", 'data-page-type="settlement-list"'),
        ("/logs/database", 'data-page-type="log-list"'),
        ("/logs/api", 'data-page-type="log-list"'),
    ],
)
def test_business_pages_use_semantic_page_types(app, path, marker):
    body = app.test_client().get(path).get_data(as_text=True)

    assert marker in body
    assert 'class="surface-card' in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest -q tests/test_ui_layout.py -k business_pages`

Expected: FAIL because the current order/settlement/log templates have generic Bootstrap cards only.

- [ ] **Step 3: Migrate order list pages**

Add a `page-header` with the existing description and new-order link. Wrap the existing table in `surface-card table-card`, keep the current columns and detail links, and render status labels with semantic classes based on the raw status:

```jinja2
<span class="status-pill status-pill--{{ order.status }}">{{ status_labels[order.status] }}</span>
```

Do not change the `status_labels` lookup or the detail URL.

- [ ] **Step 4: Migrate order forms**

Keep the single POST form and all `product_ids`, `quantity_<id>`, `unit_price_<id>`, `supplier_id`/`customer_id` inputs. Split the page visually into the party card, product-lines card, and bottom action row. Preserve the existing server-side explanatory alert and errors.

- [ ] **Step 5: Migrate order details**

Add `data-page-type="order-detail"`, a compact top summary surface card, an item table surface card, and separate fulfillment/settlement/inventory surfaces. Keep the exact existing form actions for submit, receive, and ship, and keep all conditional branches for errors, completed state, payable/receivable, and transactions.

- [ ] **Step 6: Migrate settlements and logs**

Use `data-page-type="settlement-list"` for receivables/payables and `data-page-type="log-list"` for database/API logs. Keep every current form action and button label. Use `status-pill--unpaid`, `status-pill--paid`, `status-pill--success`, and `status-pill--error` classes without removing their text labels.

- [ ] **Step 7: Run behavior tests**

Run: `pytest -q tests/test_ui_layout.py tests/test_purchase_orders.py tests/test_purchase_receipt.py tests/test_sales_orders.py tests/test_sales_shipment.py tests/test_settlements.py tests/test_logging.py`

Expected: PASS with unchanged order, inventory, settlement, and logging behavior.

### Task 5: Redesign the AI assistant surface and preserve the JavaScript contract

**Files:**
- Modify: `templates/assistant.html`
- Modify: `static/js/assistant.js`
- Modify: `static/css/style.css`
- Modify: `tests/test_ui_layout.py`

**Interfaces:**
- Consumes: Existing `assistant-chat`, `assistant-form`, `assistant-input`, `.assistant-example`, `/assistant/message`, `/assistant/confirm`, `confirmation_token`, and response shapes.
- Produces: `data-page-type="assistant"`, chip-style examples, a surface chat panel, highlighted confirmation preview cards, and unchanged AJAX behavior.

- [ ] **Step 1: Add a failing assistant page-type assertion**

Extend `test_assistant_keeps_the_javascript_contract`:

```python
def test_assistant_is_a_surface_page_with_examples(app):
    body = app.test_client().get("/assistant").get_data(as_text=True)

    assert 'data-page-type="assistant"' in body
    assert 'class="assistant-page surface-page' in body
    assert 'class="assistant-example chip' in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest -q tests/test_ui_layout.py -k assistant`

Expected: FAIL on the missing assistant page type or chip class.

- [ ] **Step 3: Migrate the assistant template**

Use a page header with the current description, keep four example button texts, and keep the existing IDs. Use the following structural contract:

```jinja2
<section class="assistant-page surface-page" data-page-type="assistant">
  <div class="page-header">
    <div><p class="eyebrow">AI WORKSPACE</p><h1>AI ERP 助手</h1><p class="page-description">用自然语言查询 ERP，订单创建会先生成预览。</p></div>
    <span class="status-pill status-pill--info">DeepSeek Agent</span>
  </div>
  <div id="assistant-chat" class="assistant-chat surface-card" aria-live="polite">
    <div class="assistant-empty text-muted">你好，我可以帮你查询库存、未收应收，或生成采购/销售订单预览。</div>
  </div>
  <div id="assistant-examples" class="assistant-examples">
    <button class="assistant-example chip" type="button">查一下机械键盘库存</button>
    <button class="assistant-example chip" type="button">向南京键盘供应商采购 100 个机械键盘，80 一个</button>
    <button class="assistant-example chip" type="button">xx科技买 20 个机械键盘，120 一个</button>
    <button class="assistant-example chip" type="button">现在还有哪些客户没付款</button>
  </div>
  <form id="assistant-form" class="assistant-composer surface-card">
    <label class="form-label" for="assistant-input">告诉 AI ERP Assistant 你要做什么</label>
    <div class="assistant-input-row">
      <input id="assistant-input" name="message" class="form-control" autocomplete="off" placeholder="例如：查一下机械键盘库存" required>
      <button class="btn btn-primary" type="submit">发送</button>
    </div>
  </form>
</section>
```

- [ ] **Step 4: Update only presentation classes in `assistant.js`**

Change `assistant-preview`, `assistant-bubble-*`, and action container class names only if the new CSS needs them. Leave the fetch URLs, HTTP methods, JSON request bodies, response type checks, confirmation token, and button event handlers unchanged.

- [ ] **Step 5: Run assistant tests**

Run: `pytest -q tests/test_ui_layout.py tests/test_agent_routes.py tests/test_agent_tools.py tests/test_deepseek_client.py`

Expected: PASS with the existing assistant route and confirmation behavior intact.

### Task 6: Full verification and visual QA

**Files:**
- Modify: any template or CSS file only if verification finds a concrete issue.

**Interfaces:**
- Consumes: All test suites and the local Flask server.
- Produces: Fresh evidence that the redesign is functionally compatible, responsive, and visually coherent across representative pages.

- [ ] **Step 1: Run the complete automated suite**

Run: `pytest -q`

Expected: Exit code 0, no failed tests, and no warnings that indicate a broken template or route.

- [ ] **Step 2: Check the final diff and whitespace**

Run: `git diff --check`

Expected: No output. Then run `git status --short` and confirm only the intended templates, CSS, optional assistant JS, and UI test file are changed.

- [ ] **Step 3: Start the local server for visual QA**

Run: `flask --app app run --debug`

Open and inspect these representative pages at desktop width and a narrow mobile width:

```text
/
/products
/products/new
/purchase-orders
/purchase-orders/new
/purchase-orders/<an existing id, if demo data exists>
/receivables
/logs/api
/assistant
```

Expected: no overlap, unreadable text, clipped buttons, or broken table scrolling; current navigation item is the only active item; empty states remain visible when the database is empty.

- [ ] **Step 4: Verify business actions still target existing endpoints**

Use the rendered HTML or browser network panel to confirm product/customer/supplier forms, order forms, settlement buttons, and assistant confirm/cancel controls still use their existing action/POST contracts. Do not create new records solely for visual QA unless an existing fixture is required.

- [ ] **Step 5: Re-run the complete automated suite after any visual fix**

Run: `pytest -q`

Expected: Exit code 0 before reporting the work as complete.
