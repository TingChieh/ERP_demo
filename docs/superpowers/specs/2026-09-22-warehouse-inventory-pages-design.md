# 仓储与库存导航模块设计

## 目标

将侧边栏中目前灰色项目的四个模块变为真实可访问页面：采购入库、销售出库、当前库存和库存流水。页面需要沿用现有 ERP 的浅色卡片式界面，并复用已经存在的订单履约事务，避免重复实现库存更新逻辑。

## 范围

本次包含：

- 待入库采购订单队列页面；
- 待出库销售订单队列页面；
- 当前库存余额页面；
- 库存流水查询页面；
- 桌面端和移动端导航链接、当前页面高亮及空状态；
- 页面级回归测试和现有全量测试验证。

本次不包含：

- 新增独立的入库单或出库单数据模型；
- 部分入库、部分出库、库存盘点、库存调整或退货；
- 改变订单状态机、库存事务、应收应付或 AI 接口；
- 增加全局搜索、筛选器、分页或导出功能。

## 现状与约束

现有业务已经提供以下履约写操作：

- `POST /purchase-orders/<order_id>/receive`：将待入库采购订单一次性入库，增加商品库存，写入入库流水，生成应付账款并完成订单；
- `POST /sales-orders/<order_id>/ship`：将待出库销售订单一次性出库，扣减商品库存，写入出库流水，生成应收账款并完成订单。

新页面只提供待处理队列和数据查询，不复制上述事务，也不直接修改 `Product.stock` 或 `InventoryTransaction`。入库/出库页面的操作按钮跳转到已有订单详情，由详情页现有 POST 表单执行实际动作。

## 页面与路由

新增一个 `inventory` blueprint，负责四个 GET 页面：

| 页面 | URL | Endpoint | 数据来源 |
| --- | --- | --- | --- |
| 采购入库 | `/purchase-receipts` | `inventory.purchase_receipts` | `PurchaseOrder(status="pending_receipt")` |
| 销售出库 | `/sales-shipments` | `inventory.sales_shipments` | `SalesOrder(status="pending_shipment")` |
| 当前库存 | `/inventory` | `inventory.current_inventory` | `Product` |
| 库存流水 | `/inventory/transactions` | `inventory.inventory_transactions` | `InventoryTransaction`，关联 `Product` |

所有队列和流水均按记录 ID 倒序显示，保证最新业务记录优先。页面不做分页，保持与当前订单、日志页面一致的最小 Demo 范围。

## 页面行为

### 采购入库

页面标题为“采购入库”，说明当前只展示已提交且等待仓库确认的采购订单。每行展示订单号、供应商、金额、创建时间、待入库状态和“处理”链接；链接指向 `purchase_orders.purchase_order_detail`。订单为空时显示明确的空状态，并提供“查看采购订单”和“新建采购订单”入口。

### 销售出库

页面标题为“销售出库”，说明当前只展示等待仓库确认的销售订单。每行展示订单号、客户、金额、创建时间、待出库状态和“处理”链接；链接指向 `sales_orders.sales_order_detail`。订单为空时显示明确的空状态，并提供“查看销售订单”和“新建销售订单”入口。

### 当前库存

页面展示所有商品的名称、SKU、当前库存和库存状态。库存大于零显示“有库存”，库存为零显示“暂无库存”；不提供库存编辑入口。页面提供“查看库存流水”“采购入库”“销售出库”三个真实导航入口，帮助用户从余额追溯到业务记录。

### 库存流水

页面展示所有库存流水，字段包括商品、SKU、类型、数量、变更后库存、关联订单和发生时间。`inbound` 显示为“入库”，`outbound` 显示为“出库”，类型同时使用带文字的状态样式。没有流水时显示空状态，并提供当前库存、采购入库和销售出库入口。

## 导航设计

桌面端在现有“业务管理”分组中保留采购订单和销售订单，并将采购入库、销售出库改为可点击链接；在“库存管理”分组中将当前库存和库存流水改为可点击链接。移动端导航包含同样的四个新链接。

导航通过 `request.endpoint` 高亮：

- 采购入库高亮 `inventory.purchase_receipts`；
- 销售出库高亮 `inventory.sales_shipments`；
- 当前库存高亮 `inventory.current_inventory`；
- 库存流水高亮 `inventory.inventory_transactions`。

所有链接保留 `data-nav-endpoint` 和匹配的 `aria-current="page"`，与现有共享壳层契约一致。

## 数据流与错误处理

1. GET 页面从 SQLAlchemy 查询只读数据并渲染 Jinja 模板。
2. 队列页的“处理”链接进入现有订单详情页。
3. 用户在订单详情页提交现有入库/出库 POST 表单。
4. 原有事务负责库存、流水、应收/应付和订单状态的原子更新。
5. 新页面不捕获或改写履约错误；用户会在已有订单详情页看到库存不足、状态不允许或重复执行等错误。

如果商品、订单或流水为空，页面返回 HTTP 200 并显示可操作的空状态，不使用异常页面代替正常空数据。页面查询不接受用户输入，因此本次不新增参数校验或错误分支。

## 模板与文件边界

预期新增或修改：

- `routes/inventory.py`：四个 GET 页面及各自查询；
- `app.py`：注册 `inventory_bp`；
- `templates/inventory/purchase_receipts.html`：采购入库队列；
- `templates/inventory/sales_shipments.html`：销售出库队列；
- `templates/inventory/current.html`：当前库存；
- `templates/inventory/transactions.html`：库存流水；
- `templates/base.html`：桌面和移动端导航链接及高亮；
- `static/css/style.css`：队列、库存、流水页面所需的共享展示样式；
- `tests/test_inventory_pages.py`：四个页面、数据展示、空状态和导航契约回归测试。

不修改：

- `models.py` 的表结构；
- `routes/purchase_orders.py` 和 `routes/sales_orders.py` 的履约事务；
- `services/`、`agent/`、现有表单字段和 POST action。

## 测试与验收

测试先锁定以下行为：

- 四个 URL 在空数据库中均返回 200，并显示对应页面标题和空状态；
- 待入库采购订单只出现在采购入库队列，待出库销售订单只出现在销售出库队列；
- 队列处理链接指向正确的订单详情页；
- 当前库存显示商品名称、SKU、库存余额和库存状态；
- 库存流水显示入库/出库文字、数量、变更后库存和关联订单；
- 新导航链接包含正确 href、`data-nav-endpoint` 和当前页 `aria-current`；
- 现有订单履约、收付款、日志、AI 和全量 UI 测试继续通过。

验收时运行 `pytest -q`，并对四个新页面以及至少一个现有订单详情页做响应式渲染检查，确认表格可横向滚动、按钮和文本没有重叠或截断。
