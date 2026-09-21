# AI ERP Assistant with DeepSeek Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DeepSeek-backed, confirmation-gated AI assistant with four safe ERP tools while preserving all existing ERP workflows.

**Architecture:** A Flask assistant blueprint calls an injectable `LLMClient`; the production adapter uses DeepSeek's OpenAI-compatible Function Calling API and tests use `MockLLMClient`. The Agent tool boundary resolves real ERP entities and computes previews, while shared order services perform the only draft-order writes after a session-backed confirmation.

**Tech Stack:** Flask 3, Flask-SQLAlchemy 3, SQLAlchemy 2, SQLite, Bootstrap 5, vanilla browser JavaScript, pytest, OpenAI Python client for DeepSeek compatibility.

## Global Constraints

- Only expose `get_inventory`, `prepare_purchase_order`, `prepare_sales_order`, and `get_unpaid_receivables` to the model.
- The model must never execute SQL, call `db.session.add()`, edit `Product.stock`, invent ERP entities, or supply a trusted total.
- Purchase and sales writes must first return a preview and require explicit confirmation.
- Purchase and sales confirmation must leave the created order in `draft` with no inventory or receivable/payable side effects.
- Missing or ambiguous entities must return clarification; the Agent may not silently choose among multiple matches.
- Existing ERP routes and tests must continue to pass without changing receipt, shipment, settlement, or dashboard rules.
- Real DeepSeek calls are isolated behind `LLMClient`; tests must use `MockLLMClient` and never need an API key or network access.
- Use `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` defaulting to `deepseek-chat`, `DEEPSEEK_BASE_URL` defaulting to `https://api.deepseek.com`, and `SECRET_KEY` for Flask sessions.

---

### Task 1: Initialize the repository and establish a verified baseline

**Files:**
- Create/modify: `.gitignore`
- Create: initial Git history and branch `feat/ai-agent-deepseek`
- Test: existing `tests/` suite

**Interfaces:**
- Consumes: existing Flask project and `requirements.txt`.
- Produces: an initialized repository, feature branch, installed dependencies, and a recorded baseline test result.

- [ ] **Step 1: Create or verify the Git repository and feature branch**

Run:

```bash
git rev-parse --show-toplevel
git status --short
git switch -c feat/ai-agent-deepseek
```

If the branch already exists, switch to it with `git switch feat/ai-agent-deepseek`.

- [ ] **Step 2: Install project dependencies**

Run:

```bash
python3 -m pip install -r requirements.txt
```

Expected: Flask, Flask-SQLAlchemy, SQLAlchemy, Jinja2, and pytest are installed without modifying application code. The OpenAI client is added and installed in Task 4 after `requirements.txt` is updated.

- [ ] **Step 3: Run the untouched baseline suite**

Run:

```bash
pytest -q
```

Expected: all existing ERP tests pass; if installation or baseline tests fail, stop and resolve that environment/code issue before implementing Agent behavior.

- [ ] **Step 4: Commit the initialized baseline**

Run:

```bash
git add .gitignore README.md app.py init_db.py models.py requirements.txt routes static templates tests docs/superpowers/specs
git commit -m "chore: initialize ERP repository and approve agent design"
```

Expected: the design and existing ERP are recorded before feature code is added.

---

### Task 2: Extract reusable draft-order services without changing existing behavior

**Files:**
- Create: `services/__init__.py`
- Create: `services/orders.py`
- Modify: `routes/purchase_orders.py`
- Modify: `routes/sales_orders.py`
- Test: `tests/test_purchase_orders.py`
- Test: `tests/test_sales_orders.py`

**Interfaces:**
- Consumes: validated form line data and the existing SQLAlchemy models.
- Produces: `create_purchase_order_draft(supplier_id: int, lines: list[dict]) -> PurchaseOrder` and `create_sales_order_draft(customer_id: int, lines: list[dict]) -> SalesOrder`, each committing one validated draft transaction.

- [ ] **Step 1: Write a failing service-level regression test for canonical draft creation**

Add tests that call the new service with a real supplier/customer and product line, then assert:

```python
order = create_purchase_order_draft(
    supplier.id,
    [{"product_id": product.id, "quantity": 2, "unit_price": Decimal("78.00")}],
)
assert order.status == "draft"
assert order.total_amount == Decimal("156.00")
assert order.items[0].product_id == product.id
```

Use the equivalent sales assertion. Also add one failing assertion that duplicate product IDs raise a validation error without leaving an order row.

- [ ] **Step 2: Run only the new service tests to verify they fail for the missing service**

Run:

```bash
pytest tests/test_purchase_orders.py tests/test_sales_orders.py -q
```

Expected: FAIL because `services.orders` and the requested functions do not exist yet.

- [ ] **Step 3: Implement the minimal shared order services**

In `services/orders.py`:

1. Resolve the supplier/customer and every product with `db.session.get`.
2. Reject missing entities, duplicate product IDs, non-positive integer quantities, negative/non-finite prices, and empty lines.
3. Calculate totals with `Decimal(quantity) * unit_price`.
4. Generate the existing `POYYYYMMDDnnn` and `SOYYYYMMDDnnn` formats.
5. Add the order and all items in one transaction, set `status="draft"`, commit, and rollback on `SQLAlchemyError`.

Do not add stock or financial rows.

- [ ] **Step 4: Make existing form routes call the shared services**

Keep `_validate_form` and its user-facing messages intact. Replace only the duplicated order construction/commit block with the corresponding service call, preserving redirect behavior and error handling.

- [ ] **Step 5: Run the focused and full existing tests**

Run:

```bash
pytest tests/test_purchase_orders.py tests/test_sales_orders.py -q
pytest -q
```

Expected: focused and all existing tests pass with no changes to receipt, shipment, or settlement behavior.

- [ ] **Step 6: Commit the reusable service extraction**

```bash
git add services routes/purchase_orders.py routes/sales_orders.py tests/test_purchase_orders.py tests/test_sales_orders.py
git commit -m "refactor: share draft order creation services"
```

---

### Task 3: Implement Agent schemas, entity resolution, and ERP tools

**Files:**
- Create: `agent/__init__.py`
- Create: `agent/schemas.py`
- Create: `agent/tools.py`
- Test: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: `models.py`, `services.orders`, and the approved four-tool contract.
- Produces: typed `AgentResponse` serialization, entity resolvers, `get_inventory`, `prepare_purchase_order`, `prepare_sales_order`, `get_unpaid_receivables`, `confirm_purchase_order`, and `confirm_sales_order`.

- [ ] **Step 1: Write failing tests for response shapes and entity resolution**

Cover these exact behaviors before implementation:

```python
response = get_inventory(product_name="机械键盘")
assert response.type == "message"
assert "80" in response.content

missing = get_inventory(product_name="不存在的商品")
assert missing.type == "clarification"
assert "不存在" in missing.message

ambiguous = get_inventory(product_name="键盘")
assert ambiguous.type == "clarification"
assert len(ambiguous.candidates) == 3
```

Use seeded products with distinct names/SKUs and assert that the tool returns no fabricated stock.

- [ ] **Step 2: Run the new tool tests to verify they fail**

```bash
pytest tests/test_agent_tools.py -q
```

Expected: FAIL because the Agent package and tool functions do not exist.

- [ ] **Step 3: Implement typed Agent response and validation schemas**

Define dataclasses or equivalent small typed structures for `message`, `clarification`, `confirmation`, and `error`. Serialize Decimal values as strings and keep database IDs only in internal pending payloads.

- [ ] **Step 4: Implement entity resolution helpers**

Implement exact normalized match, then unique substring match, then zero/multiple candidate results. Product SKU exact match has priority. Never resolve by model-supplied numeric ID.

- [ ] **Step 5: Implement read tools**

Implement `get_inventory` and `get_unpaid_receivables` using real SQLAlchemy queries. Format output only from database rows. Filter receivables by `status="unpaid"` and compute totals from returned Decimal amounts.

- [ ] **Step 6: Write failing tests for purchase and sales previews**

Assert that:

```python
preview = prepare_purchase_order(
    supplier_name="南京键盘供应商",
    items=[{"product_name": "机械键盘", "quantity": 100, "unit_price": "78"}],
)
assert preview.type == "confirmation"
assert preview.preview["total_amount"] == "7800.00"
assert PurchaseOrder.query.count() == 0
```

Add tests for default purchase/sale prices, duplicate lines, missing entities, forged total fields, and sales orders with insufficient stock.

- [ ] **Step 7: Run preview tests to verify the new cases fail**

```bash
pytest tests/test_agent_tools.py -q
```

Expected: FAIL only because preparation and confirmation behavior is not implemented.

- [ ] **Step 8: Implement prepare and confirm tools**

Preparation resolves entities, parses quantities and prices, uses product defaults when price is absent, calculates subtotals/totals with Decimal, and returns a confirmation payload with canonical IDs. It must not commit.

Confirmation accepts only the canonical payload created by preparation, re-fetches and validates all entities and line values, and delegates to the shared order services. It must never trust a client/model total.

- [ ] **Step 9: Run the tool tests and full regression suite**

```bash
pytest tests/test_agent_tools.py -q
pytest -q
```

Expected: all tool tests and all existing ERP tests pass.

- [ ] **Step 10: Commit the tool boundary**

```bash
git add agent tests/test_agent_tools.py
git commit -m "feat: add validated ERP agent tools"
```

---

### Task 4: Add DeepSeek client, prompts, and Agent orchestration

**Files:**
- Create: `agent/prompts.py`
- Create: `agent/llm.py`
- Create: `agent/service.py`
- Modify: `requirements.txt`
- Test: `tests/test_deepseek_client.py`
- Test: `tests/test_agent_tools.py`

**Interfaces:**
- Consumes: Agent response/tool functions from Task 3 and DeepSeek Chat Completions.
- Produces: `LLMClient`, `DeepSeekLLMClient`, `MockLLMClient`, `AgentService.handle_message(message) -> AgentResponse`, and an allow-listed tool registry.

- [ ] **Step 1: Write failing tests for malformed/unknown LLM actions**

Create a fake client that returns:

```python
ToolCall(name="unknown_action", arguments={})
```

and another that returns invalid JSON. Assert `AgentService.handle_message` returns `type="error"` and that no order or inventory row changes.

- [ ] **Step 2: Run the orchestration tests to verify they fail**

```bash
pytest tests/test_deepseek_client.py tests/test_agent_tools.py -q
```

Expected: FAIL because the LLM abstraction and service do not exist.

- [ ] **Step 3: Implement the system prompt and allow-listed function schemas**

In `agent/prompts.py`, state the ERP safety rules, the four function names, missing-parameter behavior, entity-resolution behavior, and unsupported high-risk operations. In `agent/service.py`, map only the four allowed names; reject all other names before any tool invocation.

- [ ] **Step 4: Implement `MockLLMClient` and `DeepSeekLLMClient`**

Use an injectable client API such as:

```python
class LLMClient(Protocol):
    def parse_message(self, message: str, *, system_prompt: str, tools: list[dict]) -> ToolCall | None | str:
        ...
```

`DeepSeekLLMClient` constructs `OpenAI(api_key=..., base_url=...)`, calls `chat.completions.create(model=..., messages=..., tools=..., tool_choice="auto", temperature=0)`, and parses one tool call or one natural-language clarification. Catch missing key, SDK/API errors, empty responses, invalid JSON, and multiple tool calls.

- [ ] **Step 5: Install the newly declared DeepSeek client dependency**

After adding `openai` to `requirements.txt`, run:

```bash
python3 -m pip install -r requirements.txt
```

Expected: the OpenAI-compatible client is available before the DeepSeek client tests run.

- [ ] **Step 6: Implement `AgentService` orchestration**

For a tool call, validate the function name and argument object, invoke the corresponding backend tool, and return its typed response. For plain text, return a safe message/clarification without claiming unverified ERP facts. Refuse unsupported receipt, shipment, collection, and payment intents.

- [ ] **Step 7: Add DeepSeek request-construction tests without network access**

Patch the OpenAI client factory with a small fake response and assert the request contains the configured base URL/model, four tool definitions, `tool_choice="auto"`, and the system prompt. Add tests for missing API key and API exception mapping.

- [ ] **Step 8: Run focused and full tests**

```bash
pytest tests/test_deepseek_client.py tests/test_agent_tools.py -q
pytest -q
```

Expected: all focused and existing tests pass without network access.

- [ ] **Step 9: Commit the DeepSeek adapter and orchestration**

```bash
git add agent requirements.txt tests/test_deepseek_client.py tests/test_agent_tools.py
git commit -m "feat: connect agent orchestration to DeepSeek"
```

---

### Task 5: Add assistant routes, session confirmation, and Bootstrap UI

**Files:**
- Create: `routes/assistant.py`
- Create: `templates/assistant.html`
- Create: `static/js/assistant.js`
- Modify: `app.py`
- Modify: `templates/base.html`
- Modify: `static/css/style.css`
- Test: `tests/test_agent_routes.py`

**Interfaces:**
- Consumes: `AgentService`, `AgentResponse`, and canonical confirm tools.
- Produces: `GET /assistant`, `POST /assistant/message`, and `POST /assistant/confirm`, plus a working assistant page.

- [ ] **Step 1: Write failing route tests**

Cover:

```python
response = client.get("/assistant")
assert response.status_code == 200

response = client.post("/assistant/message", json={"message": "查一下机械键盘库存"})
assert response.status_code == 200
assert response.json["type"] == "message"
```

Add tests that purchase/sales message requests return confirmation previews, confirmation creates exactly one draft order, cancel creates none, missing/invalid tokens fail safely, and unsupported receipt/shipment/payment intents do not mutate the database.

- [ ] **Step 2: Run route tests to verify they fail**

```bash
pytest tests/test_agent_routes.py -q
```

Expected: FAIL because the blueprint, routes, and template do not exist.

- [ ] **Step 3: Implement the assistant blueprint**

Register the blueprint in `create_app`. Read the injectable LLM client from app config, defaulting to `DeepSeekLLMClient` configured from environment. Add a development/test `SECRET_KEY` fallback only when no key is supplied.

`/assistant/message` accepts JSON or form data, invokes `AgentService`, and when the response is a confirmation stores one random token plus canonical pending payload in `session["assistant_pending_confirmation"]`.

`/assistant/confirm` accepts only the session token and `action` of `confirm` or `cancel`. Revalidate through the canonical confirm tool; never accept browser entity IDs or totals as authoritative.

- [ ] **Step 4: Implement the assistant page and browser interaction**

Render the four requested examples, append message/clarification/error responses, render preview lines and totals, and wire confirm/cancel buttons to `/assistant/confirm`. Keep the page Bootstrap-compatible and do not render raw model JSON.

- [ ] **Step 5: Add navigation and focused styling**

Add `AI 助手` to `templates/base.html` and only assistant-specific classes to `static/css/style.css`.

- [ ] **Step 6: Run route and full tests**

```bash
pytest tests/test_agent_routes.py -q
pytest -q
```

Expected: all assistant route tests and all existing ERP tests pass.

- [ ] **Step 7: Commit the assistant UI and HTTP boundary**

```bash
git add app.py routes/assistant.py templates/base.html templates/assistant.html static/js/assistant.js static/css/style.css tests/test_agent_routes.py
git commit -m "feat: add AI ERP assistant confirmation flow"
```

---

### Task 6: Verify requirements, documentation, and final repository state

**Files:**
- Modify: `README.md`
- Modify: `.gitignore` if local secret files need exclusion
- Test: all `tests/`

**Interfaces:**
- Consumes: all implemented Agent modules and test evidence.
- Produces: documented DeepSeek setup, a clean verified feature branch, and a final requirement checklist.

- [ ] **Step 1: Document local DeepSeek configuration**

Add a concise README section showing:

```bash
export DEEPSEEK_API_KEY="your-key"
export DEEPSEEK_MODEL="deepseek-chat"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export SECRET_KEY="replace-in-production"
python3 app.py
```

State that the Agent does not support receipt, shipment, collection, or payment actions and that order writes require confirmation.

- [ ] **Step 2: Run the complete verification suite**

```bash
pytest -q
python3 -m compileall app.py agent routes services tests
git diff --check
git status --short
```

Expected: pytest exits 0 with all existing and Agent tests passing, compileall exits 0, diff check prints no whitespace errors, and the status contains only intentional project files.

- [ ] **Step 3: Review the final diff against the approved spec**

Check each of the 25 Agent test requirements, confirm only four DeepSeek tools are registered, verify no Agent module edits stock or creates finance rows directly, and verify existing receipt/shipment/settlement routes are unchanged except for shared draft-service delegation.

- [ ] **Step 4: Commit documentation and final verified state**

```bash
git add README.md .gitignore app.py agent routes services static templates tests requirements.txt docs
git commit -m "docs: document DeepSeek ERP assistant setup"
```

- [ ] **Step 5: Report evidence**

Report the exact test count and command output, changed files, Agent call chain, tool-to-service boundary, entity/parameter handling, confirmation rationale, and whether all pre-existing ERP tests passed. Do not claim completion without fresh command output.

---

## Plan self-review

- Task 1 handles the requested repository initialization and baseline verification.
- Tasks 2–5 each produce a separately testable slice and preserve the approved architecture.
- Every production task starts with a failing test and includes a focused verification command.
- The service signatures used by later tasks are defined before those tasks consume them.
- The DeepSeek adapter is isolated, configurable, and network-free in tests.
- The confirmation payload and revalidation rules are explicit in the route task.
- All 25 required test behaviors are mapped across tool, client, and route tests.
- Final verification includes the full pytest suite, Python compilation, whitespace validation, and a spec diff review.
- No unresolved placeholder or unowned implementation step remains.
