# Low-Stock Analysis and AI Replenishment Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add transparent low-stock analysis, AI replenishment recommendations, supplier-aware purchase previews, and Dashboard inventory warnings without changing existing ERP order or Agent confirmation behavior.

**Architecture:** Put all replenishment queries and formulas in `services/replenishment.py`. Extend the existing Agent tool/schema/service layer to read those structured results, then reuse the current purchase confirmation session and `create_purchase_order_draft` path for the final draft-only write. The Dashboard consumes a read-only service query and links to the existing Assistant page with a prefilled prompt.

**Tech Stack:** Python 3, Flask, Flask-SQLAlchemy, SQLite, Jinja2, vanilla JavaScript, pytest.

## Global Constraints

- AI 只负责理解用户意图、解释后端计算结果和请求用户确认；ERP 后端负责查询、统计、计算、校验以及最终创建采购订单草稿。
- 只统计 `SalesOrder.status == "completed"` 的销售订单；`draft` 和 `pending_shipment` 不计入销量。
- 只统计 `PurchaseOrder.status == "pending_receipt"` 的采购订单；`draft` 和 `completed` 不计入待入库数量。
- 使用订单 `created_at` 作为现有业务时间字段；生产调用默认当前 UTC，测试传入固定 `as_of`。
- 低库存统一采用 `days_of_inventory < 7`；最近 7 天无销量时不判定为低库存，不生成基于销量的补货建议。
- `target_days` 固定为 14；`recommended_purchase_qty = max(0, ceil(target_stock - current_stock - pending_purchase_qty))`。
- 采购价优先最近真实 `PurchaseOrderItem.unit_price`，找不到历史采购价时回退 `Product.purchase_price`；LLM 不猜价格。
- 补货预览不写数据库；只有用户确认后创建 `PurchaseOrder.status == "draft"`。
- AI 补货流程不会自动提交采购订单、自动入库、自动审批、自动选择多个供应商中的一个或自动比价。
- 每个功能改动都遵循 TDD：先写一个预期失败的测试，运行并确认失败原因，再写最小实现，再运行相关测试和回归测试。
- 现有商品、供应商、客户、采购、销售、库存、财务和 Agent 行为必须继续通过原有测试。

---

### Task 1: Build the replenishment analytics service

**Files:**
- Create: `services/replenishment.py`
- Create: `tests/test_replenishment.py`

**Interfaces:**
- Consumes: `Product`, `SalesOrder`, `SalesOrderItem`, `PurchaseOrder`, `PurchaseOrderItem`, `db` from `models.py`.
- Produces:
  - `get_sales_quantity(product_id, days, as_of=None) -> int`
  - `get_pending_purchase_quantity(product_id) -> int`
  - `calculate_days_of_inventory(current_stock, avg_daily_sales_7d) -> Decimal | None`
  - `calculate_recommended_purchase_qty(current_stock, pending_purchase_qty, avg_daily_sales_7d, target_days=14) -> int`
  - `get_last_purchase_price(product_id) -> Decimal | None`
  - `analyze_replenishment(product_id, as_of=None) -> dict`
  - `get_low_stock_analyses(limit=5, as_of=None) -> list[dict]`

- [ ] **Step 1: Add the failing fixtures and sales-window tests.**

  In `tests/test_replenishment.py`, create an isolated SQLite app fixture and seed one supplier, one customer, and one product. Add completed sales orders at fixed timestamps inside and outside the 7-day/30-day windows, plus `draft` and `pending_shipment` orders. Use a fixed `as_of` so the tests do not depend on the wall clock.

  The first behavior tests must assert:

  ```python
  def test_get_sales_quantity_counts_completed_orders_in_the_requested_window(app, data):
      with app.app_context():
          assert get_sales_quantity(data["product_id"], 7, as_of=AS_OF) == 35
          assert get_sales_quantity(data["product_id"], 30, as_of=AS_OF) == 47

  def test_get_sales_quantity_excludes_draft_and_pending_shipment_orders(app, data):
      with app.app_context():
          assert get_sales_quantity(data["product_id"], 30, as_of=AS_OF) == 47
  ```

- [ ] **Step 2: Run the sales tests and verify the expected RED failure.**

  Run:

  ```bash
  pytest tests/test_replenishment.py -k sales -v
  ```

  Expected result: collection or test failure because `services.replenishment` and `get_sales_quantity` do not exist yet. Do not implement production code before observing this failure.

- [ ] **Step 3: Implement the minimal sales query.**

  In `services/replenishment.py`, calculate `cutoff = as_of - timedelta(days=days)` with UTC `datetime.now(timezone.utc)` as the default. Query `SalesOrderItem` joined to `SalesOrder`, filter by `SalesOrderItem.product_id`, `SalesOrder.status == "completed"`, and `SalesOrder.created_at >= cutoff`, then return `coalesce(sum(quantity), 0)` as an integer.

- [ ] **Step 4: Run the sales tests and verify GREEN.**

  Run:

  ```bash
  pytest tests/test_replenishment.py -k sales -v
  ```

  Expected result: all sales-window and status-filter tests pass.

- [ ] **Step 5: Add the failing pending-purchase and purchase-price tests.**

  Seed three purchase orders for the same product: a `pending_receipt` order, a `draft` order, and a `completed` order. Add a second historical purchase item with a later `created_at` and a different price. Add tests with these exact assertions:

  ```python
  def test_pending_purchase_quantity_only_counts_pending_receipt(app, data):
      with app.app_context():
          assert get_pending_purchase_quantity(data["product_id"]) == 10

  def test_last_purchase_price_uses_the_most_recent_purchase_item(app, data):
      with app.app_context():
          assert get_last_purchase_price(data["product_id"]) == Decimal("78.00")

  def test_last_purchase_price_returns_none_without_history(app, product_without_history):
      with app.app_context():
          assert get_last_purchase_price(product_without_history.id) is None
  ```

- [ ] **Step 6: Run the pending-purchase and price tests to verify RED.**

  Run:

  ```bash
  pytest tests/test_replenishment.py -k 'pending or price' -v
  ```

  Expected result: failure because the helper functions are not defined.

- [ ] **Step 7: Implement pending quantity and last-price queries.**

  Implement `get_pending_purchase_quantity` with a join from `PurchaseOrderItem` to `PurchaseOrder` and a `status == "pending_receipt"` filter. Implement `get_last_purchase_price` by joining the same tables and ordering by `PurchaseOrder.created_at.desc()`, `PurchaseOrder.id.desc()`, and `PurchaseOrderItem.id.desc()`, returning a `Decimal` unit price or `None`.

- [ ] **Step 8: Run the pending-purchase and price tests to verify GREEN.**

  Run:

  ```bash
  pytest tests/test_replenishment.py -k 'pending or price' -v
  ```

- [ ] **Step 9: Add the failing formula and edge-case tests.**

  Add tests for the exact rules:

  ```python
  def test_days_of_inventory_uses_recent_average(app):
      assert calculate_days_of_inventory(20, Decimal("5")) == Decimal("4.00")

  def test_days_of_inventory_is_none_without_recent_sales(app):
      assert calculate_days_of_inventory(0, Decimal("0")) is None

  def test_recommended_purchase_qty_uses_stock_and_pending_receipts(app):
      assert calculate_recommended_purchase_qty(20, 10, Decimal("5")) == 40

  def test_recommended_purchase_qty_is_zero_when_pending_receipt_is_enough(app):
      assert calculate_recommended_purchase_qty(5, 100, Decimal("5")) == 0

  def test_zero_stock_without_sales_is_not_low_stock(app):
      analysis = analyze_replenishment(product_without_history.id, as_of=AS_OF)
      assert analysis["days_of_inventory"] is None
      assert analysis["recommended_purchase_qty"] == 0
      assert analysis["low_stock"] is False
  ```

  Use `Decimal` for intermediate average, target, and difference calculations; round only the serialized `days_of_inventory` value to two decimal places and use `math.ceil` for the recommendation.

- [ ] **Step 10: Run the formula tests to verify RED.**

  Run:

  ```bash
  pytest tests/test_replenishment.py -k 'days or recommended or zero_stock' -v
  ```

  Expected result: failure because the formula helpers and analysis function do not exist.

- [ ] **Step 11: Implement the formula helpers.**

  Implement `calculate_days_of_inventory` to return `None` for a non-positive average, otherwise `round(Decimal(stock) / average, 2)` as a `Decimal`. Implement `calculate_recommended_purchase_qty` as `max(0, ceil(avg_daily_sales_7d * target_days - current_stock - pending_purchase_qty))`, returning an integer. When serializing the full analysis dict, convert Decimal averages and coverage values to JSON-safe numbers; keep money as two-decimal strings.

- [ ] **Step 12: Add the failing end-to-end analysis and Dashboard-list tests.**

  Add a product with current stock `20`, completed 7-day sales `35`, completed 30-day sales `35`, and pending receipt `10`. Assert that `analyze_replenishment` returns:

  ```python
  {
      "current_stock": 20,
      "sales_7d": 35,
      "sales_30d": 35,
      "avg_daily_sales_7d": 5,
      "avg_daily_sales_30d": 1.17,
      "pending_purchase_qty": 10,
      "days_of_inventory": 4,
      "recommended_purchase_qty": 40,
      "low_stock": True,
  }
  ```

  Also assert that `get_low_stock_analyses(limit=5)` returns at most five true low-stock items and does not include an item with no recent sales.

- [ ] **Step 13: Run the end-to-end service tests to verify RED.**

  Run:

  ```bash
  pytest tests/test_replenishment.py -k 'analysis or low_stock' -v
  ```

- [ ] **Step 14: Implement `analyze_replenishment` and `get_low_stock_analyses`.**

  Load the product by ID and raise `ValueError("商品不存在")` if absent. Query 7-day and 30-day sales, calculate both averages, query pending receipts, calculate coverage/recommendation, read the last price and fall back to `product.purchase_price`. Return JSON-safe values with money formatted to two decimal places and a `None` coverage for no sales. Set `low_stock` only when coverage is not `None` and below `7`. For the Dashboard list, query products in stable name/ID order, analyze each product, keep only `low_stock`, sort by coverage ascending, and return the first `limit` entries.

- [ ] **Step 15: Run the full service test file and refactor only after GREEN.**

  Run:

  ```bash
  pytest tests/test_replenishment.py -v
  ```

  Expected result: all service tests pass. Remove duplicated conversion or formatting code only after this run remains green.

- [ ] **Step 16: Commit the service deliverable.**

  ```bash
  git add services/replenishment.py tests/test_replenishment.py
  git commit -m "feat: add replenishment analytics service"
  ```

### Task 2: Add low-stock analysis and replenishment purchase tools

**Files:**
- Modify: `agent/tools.py`
- Create: `tests/test_replenishment_agent.py`

**Interfaces:**
- Consumes: `analyze_replenishment`, `get_last_purchase_price`, and `get_low_stock_analyses` from `services.replenishment`.
- Produces:
  - `analyze_low_stock(*, product_name=None) -> AgentResponse`
  - `prepare_replenishment_purchase(*, product_name=None, supplier_name=None, quantity=None) -> AgentResponse`

- [ ] **Step 1: Add failing Agent-tool tests for real analysis data.**

  In `tests/test_replenishment_agent.py`, create the same isolated app pattern as `tests/test_agent_tools.py`, seed a product with stock `20`, completed 7-day sales `35`, and pending receipt `10`. Add tests that assert:

  ```python
  def test_analyze_low_stock_returns_real_metrics(app, replenishment_data):
      with app.app_context():
          response = analyze_low_stock(product_name="机械键盘")
          assert response.type == "message"
          assert response.data["items"][0]["current_stock"] == 20
          assert response.data["items"][0]["sales_7d"] == 35
          assert response.data["items"][0]["recommended_purchase_qty"] == 40
          assert "覆盖" in response.content
          assert "待入库" in response.content

  def test_analyze_low_stock_does_not_fabricate_unknown_product(app, replenishment_data):
      with app.app_context():
          response = analyze_low_stock(product_name="不存在的商品")
          assert response.type == "clarification"
          assert response.data is None
  ```

- [ ] **Step 2: Run the Agent analysis tests and verify RED.**

  Run:

  ```bash
  pytest tests/test_replenishment_agent.py -k analyze -v
  ```

  Expected result: failure because `analyze_low_stock` is not defined.

- [ ] **Step 3: Implement `analyze_low_stock`.**

  Reuse `_resolve_product` for a specified name. For `product_name=None`, call `get_low_stock_analyses()`; for a specified product, call `analyze_replenishment(product.id)`. Build `data={"analysis_type": "replenishment", "items": items}`. For all-product results, explain that only coverage `< 7` items are listed. For a specified no-sales item, explicitly say recent 7-day sales are zero and no sales-based recommendation is generated. Record a read-only database operation log with action `analyze_low_stock`.

- [ ] **Step 4: Run the Agent analysis tests and verify GREEN.**

  Run:

  ```bash
  pytest tests/test_replenishment_agent.py -k analyze -v
  ```

- [ ] **Step 5: Add failing replenishment-preview tests.**

  Add tests that assert:

  ```python
  def test_replenishment_preview_uses_backend_recommendation_and_last_price(app, replenishment_data):
      with app.app_context():
          response = prepare_replenishment_purchase(
              product_name="机械键盘", supplier_name="南京键盘供应商"
          )
          assert response.type == "confirmation"
          assert response.action == "create_purchase_order"
          assert response.preview["items"][0]["quantity"] == 40
          assert response.preview["items"][0]["unit_price"] == "78.00"
          assert response.preview["recommendation"]["days_of_inventory"] == 4
          assert PurchaseOrder.query.count() == 0

  def test_replenishment_preview_requires_supplier_when_multiple_suppliers_exist(app, replenishment_data):
      with app.app_context():
          db.session.add(Supplier(name="另一供应商", phone=""))
          db.session.commit()
          response = prepare_replenishment_purchase(product_name="机械键盘")
          assert response.type == "clarification"
          assert len(response.candidates) == 2
          assert PurchaseOrder.query.count() == 0

  def test_single_supplier_can_be_defaulted_and_explicit_quantity_is_shown(app, replenishment_data):
      with app.app_context():
          response = prepare_replenishment_purchase(
              product_name="机械键盘", quantity=40
          )
          assert response.type == "confirmation"
          assert response.preview["supplier_name"] == "南京键盘供应商"
          assert response.preview["quantity_source"] == "user"
  ```

- [ ] **Step 6: Run the preview tests and verify RED.**

  Run:

  ```bash
  pytest tests/test_replenishment_agent.py -k preview -v
  ```

  Expected result: failure because `prepare_replenishment_purchase` is not defined.

- [ ] **Step 7: Implement supplier resolution and replenishment preview.**

  Resolve the product and re-run `analyze_replenishment` before doing anything else. Return a message response instead of confirmation when 7-day sales are zero or the computed recommendation is zero. If `supplier_name` is provided, use the existing named resolver. If it is omitted and exactly one supplier exists, use that supplier and put `supplier_source="only_supplier"` in the preview. If multiple suppliers exist, return a clarification with all supplier candidates; never select one by recency or name. Parse an explicit `quantity` as a positive integer; otherwise use `recommended_purchase_qty` and set `quantity_source="recommendation"`.

  Use `get_last_purchase_price(product.id)` and fall back to `product.purchase_price`. Build a preview with supplier, item quantity/price/subtotal, total amount, `quantity_source`, `price_source`, and a recommendation block containing current stock, sales_7d, average daily sales, coverage, pending purchase quantity, target days, and recommended quantity. Build the existing purchase payload with `supplier_id` and `product_id` only; do not add or commit any model.

- [ ] **Step 8: Run the preview tests and verify GREEN.**

  Run:

  ```bash
  pytest tests/test_replenishment_agent.py -k preview -v
  ```

- [ ] **Step 9: Add failing tests for no-sales, sufficient-pending, and price fallback behavior.**

  Assert that a zero-sales product returns a message containing “最近 7 天没有销售记录” and creates no order; a product whose pending receipt already covers the 14-day target returns a message containing “不需要补货” and creates no order; and a product with no purchase history uses its `purchase_price` with `price_source == "product_purchase_price"`.

- [ ] **Step 10: Run the edge-case tests to verify RED, then implement only the missing response branches.**

  Run first:

  ```bash
  pytest tests/test_replenishment_agent.py -k 'no_sales or sufficient or fallback' -v
  ```

  Confirm failure, add the minimal branches, then rerun the same command and expect GREEN.

- [ ] **Step 11: Run all Agent-tool tests and commit.**

  Run:

  ```bash
  pytest tests/test_agent_tools.py tests/test_replenishment_agent.py -v
  ```

  Then commit:

  ```bash
  git add agent/tools.py tests/test_replenishment_agent.py
  git commit -m "feat: add low-stock and replenishment agent tools"
  ```

### Task 3: Wire Agent schemas, service context, and confirmation safety

**Files:**
- Modify: `agent/prompts.py`
- Modify: `agent/service.py`
- Modify: `routes/assistant.py`
- Modify: `tests/test_agent_routes.py`

**Interfaces:**
- Consumes: `analyze_low_stock` and `prepare_replenishment_purchase` tool functions from Task 2.
- Produces: DeepSeek schemas for both tools, `AgentService.handle_message(message, *, context=None)`, and session-backed previous analysis context that is advisory only.

- [ ] **Step 1: Add failing route/service tests for new tool dispatch and no-write preview.**

  Extend `tests/test_agent_routes.py` with Mock LLM calls for `analyze_low_stock` and `prepare_replenishment_purchase`. Assert that a low-stock query returns real metrics, a replenishment message returns a confirmation preview, and `PurchaseOrder.query.count() == 0` before confirmation. Add a confirmation test asserting the resulting order is `draft`, with zero inventory transactions and zero payables.

- [ ] **Step 2: Run the new route tests and verify RED.**

  Run:

  ```bash
  pytest tests/test_agent_routes.py -k replenishment -v
  ```

  Expected result: failure because the new tool names are not in `ALLOWED_TOOLS` and the schemas are not exposed.

- [ ] **Step 3: Add the tool schemas and allow-list entries.**

  Add to `agent/prompts.py`:

  ```python
  _function(
      "analyze_low_stock",
      "分析真实库存、近7天/30天销量、待入库数量、覆盖天数和后端计算的补货建议。",
      {"product_name": {"type": ["string", "null"]}},
      ["product_name"],
  )
  ```

  Add a strict schema for `prepare_replenishment_purchase` with nullable `product_name`, `supplier_name`, and `quantity`. Add both functions to `ALLOWED_TOOLS` in `agent/service.py`. Update `SYSTEM_PROMPT` to require the low-stock tool for inventory facts, require a supplier choice for replenishment previews, and state that replenishment previews never create orders.

- [ ] **Step 4: Run route tests and verify GREEN for explicit product requests.**

  Run:

  ```bash
  pytest tests/test_agent_routes.py -k replenishment -v
  ```

- [ ] **Step 5: Add failing test for a follow-up request with an omitted product name.**

  In the same test client session, first return an `analyze_low_stock` response with one item, then return a `prepare_replenishment_purchase` tool call with `product_name=None`, `supplier_name=None`, and `quantity=40`. Assert that the second call produces a preview for that analyzed product and that the Mock LLM received context containing the product name. Also assert that preview generation still leaves the database unchanged.

- [ ] **Step 6: Run the context test and verify RED.**

  Run:

  ```bash
  pytest tests/test_agent_routes.py -k context -v
  ```

  Expected result: failure because the route does not save context and `AgentService.handle_message` does not accept context.

- [ ] **Step 7: Implement advisory session context.**

  Add `LAST_REPLENISHMENT_CONTEXT_KEY` in `routes/assistant.py`. After a successful message response whose `data.analysis_type == "replenishment"`, save only the returned item summaries in the signed session. Pass the saved context to `AgentService.handle_message(message, context=context)`.

  Update `AgentService.handle_message` to accept optional `context`. When present, append a clearly labeled, compact context block to the LLM input saying it is only for identifying the product and must not be trusted for inventory, sales, quantity, or price facts. The existing `MockLLMClient` signature remains compatible because it receives the same keyword arguments. The tool implementation remains the source of truth and re-runs database analysis.

- [ ] **Step 8: Run the context and full Agent route tests to verify GREEN.**

  Run:

  ```bash
  pytest tests/test_agent_routes.py tests/test_deepseek_client.py -v
  ```

- [ ] **Step 9: Add explicit safety regression tests and run them.**

  Assert that a tool call named `create_purchase_order` or an unknown write action is still rejected, and that the existing high-risk terms (`入库`, `出库`, `收款`, `付款`) still return the current refusal without mutation. Run:

  ```bash
  pytest tests/test_agent_routes.py tests/test_agent_tools.py tests/test_deepseek_client.py -v
  ```

- [ ] **Step 10: Commit the Agent wiring deliverable.**

  ```bash
  git add agent/prompts.py agent/service.py routes/assistant.py tests/test_agent_routes.py
  git commit -m "feat: wire replenishment tools into the assistant"
  ```

### Task 4: Add Dashboard inventory warnings and Assistant prompt entry

**Files:**
- Modify: `app.py`
- Modify: `templates/dashboard.html`
- Modify: `templates/assistant.html`
- Modify: `static/css/style.css`
- Modify: `static/js/assistant.js`
- Modify: `tests/test_ui_layout.py`
- Create: `tests/test_dashboard_replenishment.py`

**Interfaces:**
- Consumes: `get_low_stock_analyses(limit=5)` from Task 1.
- Produces: a read-only Dashboard warning section and a prefilled Assistant prompt that preserve all existing UI contracts.

- [ ] **Step 1: Add failing Dashboard tests.**

  Create `tests/test_dashboard_replenishment.py` with an app fixture, seed six low-stock products with distinct names and valid completed sales, plus one no-sales product. Assert:

  ```python
  def test_dashboard_shows_at_most_five_real_low_stock_products(app, replenishment_data):
      response = app.test_client().get("/")
      body = response.get_data(as_text=True)
      assert "库存预警" in body
      assert body.count('data-replenishment-row="') == 5
      assert "机械键盘" in body
      assert "推荐补货" in body
      assert "无销量商品" not in body

  def test_dashboard_warning_links_to_assistant_prompt(app, replenishment_data):
      body = app.test_client().get("/").get_data(as_text=True)
      assert "/assistant?prompt=" in body
      assert "分析机械键盘是否需要补货" in body
  ```

- [ ] **Step 2: Run the Dashboard tests and verify RED.**

  Run:

  ```bash
  pytest tests/test_dashboard_replenishment.py -v
  ```

  Expected result: failure because the Dashboard does not pass or render replenishment warnings.

- [ ] **Step 3: Wire the read-only Dashboard service query.**

  Import `get_low_stock_analyses` in `app.py`, call it with `limit=5` in the existing `dashboard` view, and pass `low_stock_items` to `dashboard.html`. Do not add SQL or formulas to the route.

- [ ] **Step 4: Render the warning section.**

  Add a `surface-card` section titled `库存预警` below the existing metric grids. For each item render a stable row marker, product name/SKU, current stock, 7-day sales, coverage (`X 天` or `近期无销量`), and recommended purchase quantity. Link to `url_for('assistant.assistant_page', prompt='分析' ~ item.product_name ~ '是否需要补货')`. Render a clear empty state when the list is empty.

- [ ] **Step 5: Run the Dashboard tests and verify GREEN.**

  Run:

  ```bash
  pytest tests/test_dashboard_replenishment.py tests/test_ui_layout.py -v
  ```

- [ ] **Step 6: Add failing Assistant prompt-prefill test.**

  Assert that `GET /assistant?prompt=分析机械键盘是否需要补货` returns an input with the escaped prompt as its value and still includes the existing `assistant-chat`, `assistant-form`, and `assistant.js` contracts.

- [ ] **Step 7: Implement prompt prefill and preview-basis rendering.**

  In `routes/assistant.py`, pass `request.args.get("prompt", "")` to `assistant.html`. In the template, set the existing input `value` from that variable with Jinja escaping. Update `static/js/assistant.js` so confirmation cards render the replenishment recommendation block when present: current stock, 7-day sales, daily average, coverage, pending receipt quantity, and recommended quantity. Use DOM text nodes or `textContent` for dynamic values; keep existing purchase/sales preview behavior unchanged. Add only the CSS needed for the compact basis block and warning card layout.

- [ ] **Step 8: Run UI tests and commit.**

  Run:

  ```bash
  pytest tests/test_dashboard_replenishment.py tests/test_ui_layout.py -v
  ```

  Then commit:

  ```bash
  git add app.py templates/dashboard.html templates/assistant.html static/css/style.css static/js/assistant.js tests/test_dashboard_replenishment.py tests/test_ui_layout.py routes/assistant.py
  git commit -m "feat: add Dashboard inventory warnings"
  ```

### Task 5: Update README and perform full regression verification

**Files:**
- Modify: `README.md`
- Create: `tests/test_replenishment_docs.py`

**Interfaces:**
- Consumes: completed service, Agent, route, and Dashboard behavior from Tasks 1-4.
- Produces: user-facing documentation of formulas, limits, safety boundaries, and test evidence.

- [ ] **Step 1: Add a documentation assertion for the replenishment rules.**

  Add `tests/test_replenishment_docs.py` that reads `README.md` and asserts it includes `target_stock`, `recommended_purchase_qty`, `pending_receipt`, `7`-day average wording, `14` days, the simple-rule/non-machine-learning limitation, and the requirement for user confirmation before draft creation.

- [ ] **Step 2: Run the documentation test and verify RED.**

  Run:

  ```bash
  pytest tests/test_replenishment_docs.py -v
  ```

  Expected result: failure because README does not yet describe the new phase.

- [ ] **Step 3: Update README with the approved rules.**

  Add the feature to the current capability list and document:

  ```text
  sales_7d = completed sales quantities in the last 7 days
  pending_purchase_qty = quantities from pending_receipt purchase orders
  days_of_inventory = current_stock / avg_daily_sales_7d, or null when there are no recent sales
  target_stock = avg_daily_sales_7d * 14
  recommended_purchase_qty = max(0, ceil(target_stock - current_stock - pending_purchase_qty))
  low_stock = days_of_inventory < 7
  ```

  Explain that the model is a transparent MVP rule based on a 7-day average, not machine learning, seasonality, or complex demand forecasting; promotions and one-off large orders can affect it. Explain that AI displays the evidence and creates only a purchase preview until the user confirms.

- [ ] **Step 4: Run the documentation test and verify GREEN.**

  Run:

  ```bash
  pytest tests/test_replenishment_docs.py -v
  ```

- [ ] **Step 5: Run targeted phase tests.**

  ```bash
  pytest tests/test_replenishment.py tests/test_replenishment_agent.py tests/test_agent_tools.py tests/test_agent_routes.py tests/test_dashboard_replenishment.py tests/test_replenishment_docs.py -q
  ```

  Expected result: zero failures.

- [ ] **Step 6: Run the complete regression suite.**

  ```bash
  pytest -q
  ```

  Expected result: all existing ERP and Agent tests plus all new phase tests pass with exit code 0.

- [ ] **Step 7: Inspect the final diff and working tree.**

  ```bash
  git diff --check
  git status --short
  git log --oneline -6
  ```

  Confirm only the approved phase files changed, no API keys or database artifacts were added, and all commits are present.

- [ ] **Step 8: Commit the documentation and verification deliverable.**

  ```bash
  git add README.md tests/test_replenishment_docs.py
  git commit -m "docs: document replenishment rules and safety boundaries"
  ```

## Final verification checklist

- [ ] Recent 7-day and 30-day completed sales are correct.
- [ ] Draft and pending-shipment sales are excluded.
- [ ] Pending-receipt purchase quantities are correct; draft/completed purchases are excluded.
- [ ] Coverage is `null` with no recent sales and zero-stock/no-sales is not low stock.
- [ ] Recommendation uses the 14-day target, current stock, pending receipts, and ceiling.
- [ ] Recent purchase price and Product fallback are correct.
- [ ] `analyze_low_stock` returns real structured data and explanatory text.
- [ ] `prepare_replenishment_purchase` only creates a preview and requires supplier selection when needed.
- [ ] User confirmation creates only a draft purchase order.
- [ ] No automatic submission, receipt, payable, approval, supplier comparison, or forecasting is added.
- [ ] Dashboard shows at most five real warnings and links to the Assistant prompt.
- [ ] New tests pass.
- [ ] Existing ERP and Agent tests pass.
