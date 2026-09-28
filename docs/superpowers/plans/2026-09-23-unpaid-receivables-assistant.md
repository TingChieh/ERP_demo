# AI 助手未付款客户查询 Implementation Plan

> **For agentic workers:** Implementation completed in the current workspace. Checkboxes record completed steps.

**Goal:** 让 AI 助手正确回答未付款客户查询，并显示应收明细和页面入口，同时继续拒绝收款、付款等写操作。

**Architecture:** `AgentService` 在调用 LLM 前区分未收款状态查询和明确结算动作；`get_unpaid_receivables` 返回完整数据库明细并生成可独立阅读的摘要；浏览器将明细安全地渲染为链接卡片。查询继续使用现有 `AccountReceivable` 数据和 Function Calling。

**Tech Stack:** Python 3, Flask, SQLAlchemy, vanilla JavaScript, pytest。

## Global Constraints

- 查询范围只包含 `AccountReceivable.status == "unpaid"`。
- 客户、订单、金额和时间全部来自数据库；金额合计继续使用 `Decimal`。
- 明确收款/付款/支付/结算动作在 LLM 调用前拒绝。
- 入库、出库和发货请求继续在 LLM 调用前拒绝。
- 前端使用 DOM `textContent` 写入返回值，不用 `innerHTML`。
- 不修改数据库模型、结算路由或其他订单业务规则。

## File Map

- Modify: `agent/service.py` — 只读未收款查询和明确结算动作的安全意图判定。
- Modify: `agent/tools.py` — 返回应收记录 ID、订单 ID 及完整可展示明细和摘要。
- Modify: `static/js/assistant.js` — 显示客户应收列表、订单详情链接和应收页面入口。
- Modify: `templates/assistant.html` — 将能力说明明确为查询未收应收。
- Modify: `tests/test_agent_routes.py` — 覆盖自然语言查询可达工具、结算动作被拦截且不调用 LLM。
- Modify: `tests/test_agent_tools.py` — 覆盖完整明细、摘要、客户过滤和空结果。
- Modify: `tests/test_ui_layout.py` — 覆盖助手页面的应收账款入口和查询能力文案。

---

### Task 1: Lock the read-only query and write-action boundary with tests

**Files:**
- Modify: `tests/test_agent_routes.py`
- Modify: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `AgentService`, `ToolCall`, existing temporary SQLite fixtures, `AccountReceivable` and order models.
- Produces: failing tests for the approved unpaid-query phrases, action refusals, detailed query payload and empty results.

- [x] Add route tests for `现在还有哪些客户没付款`, `现在还有哪些客户没有付款`, and `帮我查一下哪些客户没付款`; assert the customer/order/amount response and one LLM call.
- [x] Add a route test for `xx科技还欠多少钱` that returns only that customer's receivables through `get_unpaid_receivables`.
- [x] Strengthen the explicit-action test for `确认收款`, `确认付款`, `执行付款`, `支付给xx科技`, and direct collection phrases; assert the mock LLM has no calls.
- [x] Extend the tool test to assert `receivable_id`, `sales_order_id`, `sales_order_no`, customer, amount and created time, and that `content` names the customer and amount.
- [x] Add an empty query test that asserts a successful message, zero items and a zero total.
- [x] Run the focused route/tool tests and observe the expected red failure before implementation.

### Task 2: Implement safe intent routing and complete query responses

**Files:**
- Modify: `agent/service.py`
- Modify: `agent/tools.py`
- Test: `tests/test_agent_routes.py`, `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: user message string, existing `get_unpaid_receivables(*, customer_name=None)` tool, SQLAlchemy receivable relationships.
- Produces: private intent helpers in `AgentService`; each query item has `receivable_id`, `sales_order_id`, `sales_order_no`, `customer`, `amount`, and ISO `created_at`.

- [x] Add an unpaid-query classifier for unpaid/status phrases paired with query cues, including both “没付款” and “没有付款”.
- [x] Add an explicit settlement-action classifier for collection, payment, transfer and settlement commands.
- [x] Keep refusing 入库/出库/发货 and reject other settlement requests before invoking the LLM.
- [x] Extend the `get_unpaid_receivables` items with both IDs and preserve ISO timestamps.
- [x] Build `content` from verified customer/order/amount/time values and retain the no-unpaid message.
- [x] Run focused route/tool tests and verify read queries reach the tool while explicit writes make zero LLM calls.

### Task 3: Render the query details and verify the full feature

**Files:**
- Modify: `static/js/assistant.js`
- Modify: `templates/assistant.html`
- Modify: `tests/test_ui_layout.py`
- Test: all Agent and UI tests

**Interfaces:**
- Consumes: message response `data={"query_type": "unpaid_receivables", "total_amount": str, "items": [...]}`.
- Produces: a DOM card for responses with `query_type="unpaid_receivables"`, with one customer, order, amount, and timestamp row per item; order links target `/sales-orders/<sales_order_id>` and the card includes `/receivables`.

- [x] Add a renderer for unpaid receivable responses using DOM creation and `textContent`; construct sales order links from numeric IDs.
- [x] Display the total and “查看应收账款” link; skip the card for an empty list.
- [x] Update assistant copy to describe read-only unpaid receivable queries and direct users to the receivables page for collection.
- [x] Add UI copy assertions and smoke the renderer with a mocked response, checking both links and displayed amount.
- [x] Run focused tests and the complete repository suite: 254 tests passed.
- [x] Review `git diff --check` and preserve the workspace's unrelated pre-existing changes. Leave implementation files uncommitted because existing user edits overlap several of them.
