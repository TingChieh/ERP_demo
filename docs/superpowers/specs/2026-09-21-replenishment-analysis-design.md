# 第十阶段：低库存分析与 AI 补货建议设计

## 目标

在不破坏现有 ERP 业务逻辑和 Agent 逻辑的前提下，基于真实的销售、库存和采购数据，提供可解释的低库存分析、补货建议和采购订单预览。

AI 只负责理解用户意图、解释后端计算结果和请求用户确认；ERP 后端负责查询、统计、计算、校验以及最终创建采购订单草稿。

本阶段不实现自动采购、自动提交、自动入库、自动审批、复杂需求预测、多仓库或供应商比价。

## 已确认的实现路径

采用独立的 replenishment service，并复用现有 Agent 采购预览和确认链路：

1. `services/replenishment.py` 负责所有补货分析查询和公式计算。
2. Agent tool 只调用 replenishment service，不能自行编造库存、销量、采购数量或价格。
3. 补货预览沿用现有 `create_purchase_order` confirmation action。
4. 只有用户确认后，才调用现有 `create_purchase_order_draft` 创建 `PurchaseOrder(status="draft")`。
5. Dashboard 服务端渲染最多 5 个低库存商品，并链接到已有 Assistant 页面。
6. Assistant session 可以保存最近一次分析结果，仅用于识别后续“那就帮我补 40 个”中的商品；准备预览时必须重新查询数据库。

## 数据分析边界

### 时间口径

当前模型没有单独的完成时间字段，因此使用订单的 `created_at` 作为已有业务时间字段。

- `as_of` 默认为当前 UTC 时间。
- 最近 7 天窗口为 `created_at >= as_of - timedelta(days=7)`。
- 最近 30 天窗口为 `created_at >= as_of - timedelta(days=30)`。
- 测试可以传入固定 `as_of`，避免依赖系统时间。

### 销量统计

只统计满足以下条件的 `SalesOrderItem.quantity`：

- 所属 `SalesOrder.status == "completed"`；
- 商品为目标商品；
- 销售订单 `created_at` 位于对应时间窗口内。

`draft` 和 `pending_shipment` 销售订单不计入销量。

### 待入库统计

只统计满足 `PurchaseOrder.status == "pending_receipt"` 的 `PurchaseOrderItem.quantity`。

`draft` 和 `completed` 采购订单不计入待入库数量。

### 分析指标和公式

对于每个 Product，后端计算：

```text
current_stock = Product.stock
sales_7d = 最近 7 天已完成销售数量
sales_30d = 最近 30 天已完成销售数量
avg_daily_sales_7d = sales_7d / 7
avg_daily_sales_30d = sales_30d / 30
pending_purchase_qty = 待入库采购数量
```

库存覆盖天数：

```text
如果 avg_daily_sales_7d > 0：
    days_of_inventory = current_stock / avg_daily_sales_7d
否则：
    days_of_inventory = null
```

第一版固定 `target_days = 14`：

```text
target_stock = avg_daily_sales_7d * 14
available_future_stock = current_stock + pending_purchase_qty
recommended_purchase_qty = max(
    0,
    ceil(target_stock - available_future_stock)
)
```

低库存统一采用库存覆盖天数规则：

```text
low_stock = days_of_inventory is not null and days_of_inventory < 7
```

最近 7 天无销量时：

- `days_of_inventory = null`；
- `recommended_purchase_qty = 0`；
- `low_stock = false`；
- 文案说明“最近 7 天没有销售记录，暂不基于销量生成补货建议”。

库存为 0 但近期无销量时，不仅凭库存为 0 判定低库存。

### 采购价格

`get_last_purchase_price(product_id)` 从最近的 `PurchaseOrderItem` 真实数据读取该商品的 `unit_price`，按照所属采购订单的 `created_at`、订单 ID 和明细 ID 倒序确定最近记录。

如果没有任何历史采购明细，则回退到 `Product.purchase_price`。LLM 不参与价格计算或猜测。

## Service 接口

`services/replenishment.py` 提供以下职责清晰的函数：

- `get_sales_quantity(product_id, days, as_of=None)`
- `get_pending_purchase_quantity(product_id)`
- `calculate_days_of_inventory(current_stock, avg_daily_sales_7d)`
- `calculate_recommended_purchase_qty(current_stock, pending_purchase_qty, avg_daily_sales_7d, target_days=14)`
- `get_last_purchase_price(product_id)`
- `analyze_replenishment(product_id, as_of=None)`
- 面向 Dashboard 的低库存列表查询函数，返回按低库存程度排序、最多 5 条的分析字典。

分析字典包含：

```json
{
  "product_id": 1,
  "product_name": "机械键盘",
  "sku": "KB001",
  "current_stock": 20,
  "sales_7d": 35,
  "sales_30d": 35,
  "avg_daily_sales_7d": 5,
  "avg_daily_sales_30d": 1.17,
  "pending_purchase_qty": 10,
  "days_of_inventory": 4,
  "recommended_purchase_qty": 40,
  "default_purchase_price": "80.00",
  "last_purchase_price": "78.00",
  "purchase_price": "78.00",
  "low_stock": true
}
```

金额以可 JSON 序列化的两位小数字符串返回；数量为整数；覆盖天数为有限小数或 `null`。

## Agent 流程

### `analyze_low_stock`

工具参数：

```json
{"product_name": null}
```

`null` 表示分析全部商品；指定商品时使用现有商品解析规则，找不到或名称歧义时返回 clarification，不编造商品。

返回结构化 `data.items`。查询全部商品时只返回 `low_stock == true` 的商品；查询指定商品时返回该商品完整指标，即使当前不低库存。

自然语言结果必须说明：

- 当前库存；
- 最近 7 天销量；
- 平均日销量；
- 库存覆盖天数，或近期无销量；
- 待入库数量；
- 推荐补货数量；
- 推荐或不推荐的原因。

### `prepare_replenishment_purchase`

工具参数：

```json
{
  "product_name": "机械键盘",
  "supplier_name": null,
  "quantity": null
}
```

后端流程：

1. 解析并校验商品；如果商品名来自上一轮 session 上下文，也必须再次通过数据库解析。
2. 重新运行 `analyze_replenishment`。
3. 最近 7 天无销量或推荐数量为 0 时，不生成采购预览并返回解释。
4. `quantity == null` 时使用后端计算的 `recommended_purchase_qty`。
5. 用户明确提供数量时，只接受正整数，并在预览中标明“用户指定数量”；该数量不是 LLM 计算出来的事实。
6. 供应商由用户选择；系统只有一个供应商时才可以默认，并在预览中说明；多个供应商时返回候选要求选择。
7. 使用最近采购价，缺失时使用商品默认采购价。
8. 生成包含供应商、商品、数量、单价、金额和推荐依据的 confirmation preview；不写数据库。

返回的 confirmation action 使用现有的 `create_purchase_order`，以复用现有确认 endpoint。用户点击确认后，才调用现有 `confirm_purchase_order` 和 `create_purchase_order_draft`。

### Session 上下文

Assistant route 在成功完成低库存分析后，可保存最近分析的结构化结果，用来帮助 LLM 理解省略商品名的下一条请求。上下文只用于意图识别，不用于库存、销量、数量或价格事实；预览工具每次都重新读取数据库。

## Dashboard

在现有 Dashboard 指标下方新增“库存预警”区域：

- 最多展示 5 个 `low_stock` 商品；
- 显示商品、SKU、当前库存、近 7 天销量、覆盖天数、推荐补货数量；
- 无预警时显示空状态；
- 点击商品链接到 `/assistant?prompt=分析<商品>是否需要补货`；
- route 只调用 replenishment service，不直接编写补货 SQL 或公式。

Assistant 页面读取 `prompt` 查询参数并预填输入框，现有发送和确认接口保持不变。

## 测试策略

### Service 测试

覆盖最近 7 天和 30 天销量、completed 状态过滤、draft/pending_shipment 排除、pending_receipt 待入库、draft/completed 采购排除、覆盖天数、无销量、推荐数量、待入库抵扣、待入库充足归零、低库存判定和最近采购价回退。

### Agent 和 route 测试

覆盖真实数据库分析、全部商品和指定商品、缺失/歧义商品、Agent 不编造库存销量、补货预览无数据库写入、确认后才创建采购订单、创建状态为 draft、不会提交或入库、供应商选择、价格来源和会话上下文。

### Dashboard/UI 测试

覆盖库存预警真实数据、最多 5 条、关键字段、Assistant prompt 跳转以及现有 UI contract。

最后执行完整 `pytest -q`，确认原有 ERP 和 Agent 测试继续通过。

## README 说明

README 将明确说明本阶段使用最近 7 天平均销量的简单、透明规则模型：

- 容易理解、解释和验证；
- 适合 MVP；
- 避免 AI 黑盒直接决定采购；
- 不是机器学习预测、季节性模型或复杂需求预测；
- 促销或一次性大订单可能影响 7 天平均值。

README 同时明确：AI 不直接下采购单，只有用户确认补货预览后才创建采购订单草稿；草稿仍需现有 ERP 流程提交和后续入库。
