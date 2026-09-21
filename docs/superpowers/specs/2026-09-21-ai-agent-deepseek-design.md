# AI ERP Assistant with DeepSeek — Design Specification

**Date:** 2026-09-21  
**Status:** Approved for implementation planning  
**Scope:** ERP Phase 9 — the first AI Agent layer

## Goal

Add a safe AI assistant to the existing Flask ERP MVP. The assistant accepts Chinese natural-language requests, uses DeepSeek Function Calling to select one of four allowed ERP capabilities, validates all arguments against real ERP data, returns read results or write previews, and only creates draft orders after an explicit user confirmation.

The existing ERP behavior must remain unchanged. The existing Product, Supplier, Customer, purchase, sales, inventory, settlement, and dashboard workflows are not replaced or broadened.

## Non-goals

This phase does not add:

- AI purchase receipt or sales shipment;
- AI customer collection or supplier payment;
- stock editing;
- product, customer, or supplier creation;
- deletion or arbitrary data modification;
- SQL generation or SQL execution by the model;
- RAG, vector search, MCP, multi-agent workflows, long-term memory, or autonomous loops;
- a general reporting or analytics agent.

## Core safety rule

The model is an intent and parameter extraction layer only. It may select an allowed ERP tool and explain a verified result, but it may never execute SQL, call `db.session.add()`, edit `Product.stock`, invent ERP entities, calculate a trusted total, bypass status checks, or confirm a high-risk operation itself.

The trusted flow is:

```text
natural language
  -> DeepSeek Function Calling
  -> application-side action and argument validation
  -> real ERP entity resolution
  -> read result or write preview
  -> explicit browser confirmation
  -> application-side revalidation
  -> existing order creation service
  -> database
```

## Architecture

The Agent layer is isolated from the existing routes and models.

```text
routes/assistant.py
        |
        v
agent/service.py -------- agent/llm.py -------- DeepSeek API
        |
        +-------- agent/tools.py -------- models.py / services/orders.py
        |
        +-------- agent/schemas.py / agent/prompts.py
```

The LLM client is an injectable interface. Production uses `DeepSeekLLMClient`; tests use `MockLLMClient`. The LLM client does not know SQLAlchemy models. `agent/tools.py` is the only Agent-facing ERP boundary, and write confirmation delegates to shared order business functions rather than writing records inline.

## Allowed Agent capabilities

Only these four functions are exposed to DeepSeek:

1. `get_inventory`
2. `prepare_purchase_order`
3. `prepare_sales_order`
4. `get_unpaid_receivables`

The word `prepare` is intentional: order creation is not exposed as a direct model action. Internal functions named `confirm_purchase_order` and `confirm_sales_order` may be used by the confirmation route, but they are not registered in the DeepSeek tool list.

## DeepSeek integration

Use DeepSeek's OpenAI-compatible Chat Completions API with the official `openai` Python client.

Configuration:

| Setting | Environment variable | Default |
| --- | --- | --- |
| API key | `DEEPSEEK_API_KEY` | unset |
| model | `DEEPSEEK_MODEL` | `deepseek-chat` |
| base URL | `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| application secret | `SECRET_KEY` | development-only fallback |

The client sends the system prompt, the user message, and the four tool schemas with `tool_choice="auto"`. Tool schemas use JSON Schema and strict validation where supported; application-side validation remains mandatory because an API response can still be malformed or contain unsupported values. A single user message is expected to result in at most one tool call. Multiple tool calls are rejected safely for this MVP.

The client uses a deterministic low-variance configuration (`temperature=0` where supported) and does not expose a thinking/reasoning trace to the user. The application formats verified query results and order previews itself instead of displaying raw model JSON or asking the model to invent a final numeric result.

If the API key is missing, the client returns a configuration error. The app remains renderable and testable; tests inject `MockLLMClient` and never call the network. Network failures, timeouts, empty content, malformed JSON, unknown tool names, and invalid tool arguments all become safe `error` responses with no business side effects.

DeepSeek references:

- [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)

## Agent response contract

`agent/schemas.py` defines typed internal response objects and JSON serialization for these public response shapes:

```json
{"type": "message", "content": "机械键盘（KB001）当前库存是 80 个。"}
```

```json
{
  "type": "confirmation",
  "action": "create_purchase_order",
  "confirmation_token": "...",
  "preview": {
    "supplier_name": "南京键盘供应商",
    "items": [
      {
        "product_name": "机械键盘",
        "sku": "KB001",
        "quantity": 100,
        "unit_price": "78.00",
        "subtotal": "7800.00",
        "price_source": "user"
      }
    ],
    "total_amount": "7800.00"
  }
}
```

```json
{
  "type": "clarification",
  "message": "系统中没有找到客户“老王”，请确认客户名称。",
  "candidates": []
}
```

```json
{"type": "error", "message": "暂时无法处理该请求，请稍后重试。"}
```

The browser never receives the model's raw action JSON as the user-facing answer.

## Entity resolution

The application, not DeepSeek, decides which database entity is used.

For products:

1. exact SKU match when `sku` is provided;
2. exact normalized product-name match;
3. unique normalized substring match;
4. zero matches returns a clarification stating that the product does not exist;
5. multiple matches returns a clarification with candidate names and SKUs.

Supplier and customer resolution uses exact normalized name first, then unique substring match. Zero matches and multiple matches are clarifications. IDs supplied by the model are not accepted as authoritative input.

Normalization trims whitespace and uses case-insensitive matching where applicable. No fuzzy match may silently choose among multiple candidates.

## Tool behavior

### `get_inventory`

Input accepts `product_name` and/or `sku`. The tool must resolve one real `Product`, then return its database ID, name, SKU, and current `stock`. A missing or ambiguous product returns a clarification and never fabricates a stock value.

### `prepare_purchase_order`

Input contains `supplier_name` and a non-empty list of item requests. Each item identifies a product by name or SKU, has a positive integer quantity, and may omit `unit_price`.

The tool must:

- resolve a real `Supplier` and real `Product` rows;
- reject missing or ambiguous entities;
- reject duplicate products in one order;
- reject non-positive or non-integer quantities;
- reject negative, non-finite, or malformed prices;
- use `Product.purchase_price` when the price is omitted;
- mark defaulted prices as `price_source="default_purchase_price"` in the preview;
- calculate each subtotal and the total with backend `Decimal` arithmetic;
- return a confirmation preview without creating a `PurchaseOrder`, item, payable, inventory transaction, or stock change.

### `prepare_sales_order`

Input contains `customer_name` and item requests using the same product, quantity, duplicate, and price rules. Omitted prices use `Product.sale_price` and are marked as `default_sale_price`.

The tool does not inspect inventory for eligibility, does not reserve stock, does not decrement stock, and does not create an `AccountReceivable`. Inventory shortage is allowed at order-creation time because a sales order is not a shipment.

### `get_unpaid_receivables`

With no customer name, query all `AccountReceivable` rows with `status="unpaid"`. With a customer name, resolve the real `Customer` first and filter unpaid rows by that customer. Return verified order number, customer name, amount, and creation time, plus a backend-summed total. If no rows match, return an explicit no-outstanding-receivables message.

## Confirmation and persistence

`POST /assistant/message` stores one pending confirmation in the signed Flask session. The stored payload contains only canonical database IDs, quantities, explicit unit prices, action, and a random confirmation token. It does not rely on browser-displayed names or totals.

`POST /assistant/confirm` accepts the token and either `confirm` or `cancel`:

- `cancel` removes the pending payload and makes no database change;
- `confirm` verifies the token, re-fetches supplier/customer/product rows, revalidates quantities and prices, recalculates the total using `Decimal`, and invokes the shared order service;
- a missing, expired/replaced, or mismatched token returns an error and writes nothing;
- successful purchase creation leaves the order in `draft` and creates no stock, inventory, or payable rows;
- successful sales creation leaves the order in `draft` and creates no stock, inventory, or receivable rows.

The session is signed by Flask. The application secret must be supplied through `SECRET_KEY` outside development and tests.

## Shared order business services

The current purchase and sales form routes contain order-number generation and draft-order persistence inline. Extract only the reusable creation boundary into `services/orders.py`:

- `create_purchase_order_draft(supplier_id, lines) -> PurchaseOrder`
- `create_sales_order_draft(customer_id, lines) -> SalesOrder`

Each service defensively validates canonical IDs, positive quantities, finite non-negative `Decimal` unit prices, duplicate product IDs, and computes the total from line values before committing one transaction. It generates the same order-number format as the existing routes and leaves status as `draft`.

The existing form routes continue to perform their current user-facing validation and call these services. Existing receipt, shipment, receivable, and payable workflows remain in their current routes and are not callable through Agent tools.

## HTTP routes and UI

Add `routes/assistant.py` with:

- `GET /assistant`: render the assistant page;
- `POST /assistant/message`: accept a message and return serialized `AgentResponse` JSON;
- `POST /assistant/confirm`: accept a pending confirmation token and `confirm`/`cancel`, then return JSON with the result or error.

Add `templates/assistant.html` with the existing Bootstrap layout, chat history, input form, send button, four preset example prompts, confirmation preview cards, and confirm/cancel controls.

Add `static/js/assistant.js` for the minimal fetch-based message/confirmation interaction. The page must display response types as user-facing Chinese text and must not expose raw LLM payloads.

Add only the assistant-specific CSS in `static/css/style.css`, and add an `AI 助手` link to `templates/base.html`.

## Planned file changes

Create:

- `agent/__init__.py`
- `agent/schemas.py`
- `agent/prompts.py`
- `agent/llm.py`
- `agent/tools.py`
- `agent/service.py`
- `services/__init__.py`
- `services/orders.py`
- `routes/assistant.py`
- `templates/assistant.html`
- `static/js/assistant.js`
- `tests/test_agent_tools.py`
- `tests/test_agent_routes.py`
- `tests/test_deepseek_client.py`

Modify:

- `app.py`: register the assistant blueprint, configure the secret, and inject the default LLM client through app configuration.
- `routes/purchase_orders.py`: preserve existing form behavior while delegating canonical draft creation to the shared service.
- `routes/sales_orders.py`: preserve existing form behavior while delegating canonical draft creation to the shared service.
- `templates/base.html`: add the AI Assistant navigation link.
- `static/css/style.css`: add assistant layout styles only.
- `requirements.txt`: add the OpenAI Python client needed for the DeepSeek-compatible API.

## Error handling

The service must return a safe response rather than raise an unhandled exception for:

- missing DeepSeek API key;
- DeepSeek timeout, connection error, API error, empty response, malformed tool arguments, or unknown tool name;
- missing or ambiguous ERP entities;
- invalid quantities, prices, duplicate lines, or missing required business parameters;
- missing or invalid confirmation token;
- SQLAlchemy failure during order creation.

Before returning an error, the service must roll back any active database transaction. No error path may partially create an order, change stock, create an inventory transaction, or create a receivable/payable.

Unsupported high-risk requests such as “把 PO 入库”, “把 SO 发货”, “确认收款”, and “确认付款” must return an explicit unsupported-operation response directing the user to the existing ERP detail page. They must not be mapped to a nearby allowed tool.

## Testing strategy and acceptance criteria

All tests use a temporary SQLite database. Agent route tests inject `MockLLMClient`; no test calls DeepSeek or requires an API key.

Required new coverage:

1. `/assistant` returns 200.
2. Existing product inventory query returns the real stock.
3. Missing product never returns fabricated stock.
4. Ambiguous product names return candidates.
5. Natural-language purchase input produces a preview.
6. Purchase preview does not create a `PurchaseOrder`.
7. Purchase confirmation creates the draft order.
8. A forged model total is ignored and backend total wins.
9. Missing supplier blocks purchase creation.
10. Missing product blocks purchase creation.
11. Missing purchase price uses `purchase_price`.
12. Natural-language sales input produces a preview.
13. Sales preview does not create a `SalesOrder`.
14. Sales confirmation creates the draft order.
15. Insufficient stock does not block sales-order creation.
16. Missing customer blocks sales creation.
17. Missing sales price uses `sale_price`.
18. All unpaid receivables query is correct.
19. Customer-filtered unpaid receivables query is correct.
20. Purchase receipt action is refused.
21. Sales shipment action is refused.
22. Customer collection action is refused.
23. Supplier payment action is refused.
24. Malformed LLM output fails safely.
25. Unknown LLM action performs no business operation.

The complete existing ERP test suite must continue to pass without changing its business rules. Completion requires all new Agent tests and all existing tests to pass.

## Spec self-review

- Scope is one bounded subsystem: the first Agent layer with four tools and a confirmation flow.
- DeepSeek is isolated behind `LLMClient`; tests do not depend on network access.
- No model-generated entity ID or total is treated as trusted.
- Read tools and prepare tools are distinct from confirmation functions.
- The draft status and no-side-effect rules are explicit for both order types.
- High-risk workflows are named and excluded from the tool registry.
- Missing configuration, malformed model output, ambiguity, missing data, and transaction errors have defined outcomes.
- Planned files, service signatures, routes, environment variables, and test coverage are explicit.
- No `TODO`, `TBD`, or unresolved implementation choice remains in this specification.
