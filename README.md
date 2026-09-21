# ERP Demo

这是一个面向学习和面试演示的最小 ERP Demo，使用 Flask、SQLite、SQLAlchemy、Jinja2 和 Bootstrap 5 构建。

当前阶段只包含：

- Flask 应用初始化
- SQLite 数据库和确认后的基础数据模型
- 初始化数据库和演示基础数据
- 只读 Dashboard
- 商品、供应商、客户基础资料的列表、新增和编辑
- 采购订单的列表、新建、详情查看和草稿提交
- 待入库采购订单的确认入库、库存流水和应付账款生成
- 销售订单的列表、新建、详情查看和草稿提交
- 待出库销售订单的确认出库、库存流水和应收账款生成
- 应收账款和应付账款列表、整笔收款和整笔付款
- DeepSeek AI ERP Assistant：库存查询、采购/销售订单预览、未收应收查询
- 补货分析：低库存预警、补货建议和采购预览

当前阶段暂不包含部分收款、部分付款、多次收款、多次付款、发票、对账、退款、退货、现金流和银行账户模块。

## 启动方式

在项目根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python init_db.py
flask --app app run --debug
```

然后打开 <http://127.0.0.1:5000>。

基础资料页面：

- `/products`：商品管理
- `/suppliers`：供应商管理
- `/customers`：客户管理
- `/purchase-orders`：采购订单
- `/purchase-orders/new`：新建采购订单
- `/sales-orders`：销售订单
- `/sales-orders/new`：新建销售订单

财务结算页面：

- `/receivables`：应收账款和确认收款
- `/payables`：应付账款和确认付款

AI 助手页面：

- `/assistant`：自然语言 ERP 助手

系统日志页面：

- `/logs/database`：ERP 业务数据库操作审计日志
- `/logs/api`：DeepSeek API 调用元数据日志

日志默认只保存动作、实体、状态、耗时、HTTP 状态、request id 和 token 数量，不保存 API Key、完整 Prompt、完整响应或工具参数。更新代码后如果是已有本地数据库，请重新运行一次 `python init_db.py` 创建新增日志表。

## DeepSeek 配置

AI 助手通过 DeepSeek 的 OpenAI-compatible Chat Completions 接口进行 Function Calling。启动前配置：

```bash
export DEEPSEEK_API_KEY="your-key"
export DEEPSEEK_MODEL="deepseek-chat"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export SECRET_KEY="replace-in-production"
python app.py
```

也可以直接复制项目根目录的 `.env.example` 为 `.env`，然后填写 `DEEPSEEK_API_KEY`；应用启动时会自动读取 `.env`。`.env` 已加入 `.gitignore`，不会提交 API Key。

当前 AI 助手只支持库存查询、低库存分析、补货采购预览、采购订单预览、销售订单预览和未收应收查询。采购、销售或补货采购订单必须先由助手生成预览，再点击确认创建草稿；助手不会直接执行采购入库、销售出库、收款或付款。

### 补货分析规则

补货分析使用透明的 simple rule 和 7-day average；it is not machine learning and does not use seasonality or complex demand forecasting。促销活动和一次性大额订单可能影响结果。具体计算如下：

```text
sales_7d = completed sales quantities in the last 7 days
pending_purchase_qty = quantities from pending_receipt purchase orders
days_of_inventory = current_stock / avg_daily_sales_7d, or null when there are no recent sales
target_stock = avg_daily_sales_7d * 14
recommended_purchase_qty = max(0, ceil(target_stock - current_stock - pending_purchase_qty))
low_stock = days_of_inventory < 7
```

其中目标库存覆盖 14 days。AI 会展示计算依据，并且只创建采购预览；必须经过 user confirmation before draft creation，才会创建采购草稿，不会自动提交、入库或执行其他采购履约动作。

测试通过注入 Mock LLM，不需要 DeepSeek API Key，也不会访问网络。

收款和付款只会将对应财务记录从未结算变为已结算，并记录时间，不会修改库存、库存流水或采购/销售订单履约状态。

销售订单进入“待出库”后，可以在详情页确认出库。系统会先校验整张订单的全部商品库存；全部充足后，在一个事务中扣减库存、生成出库流水、创建一笔未收款应收账款，并将订单改为“已完成”。如果任意商品不足或中途失败，整单不会发生变化。

本 Demo 使用 SQLite，暂不实现生产级并发库存锁。真实 ERP 通常会使用数据库行锁、原子 UPDATE 或乐观锁，避免多个订单同时出库造成超卖。

采购订单进入“待入库”后，可以在详情页确认入库。确认入库会在一个事务中同时更新商品库存、生成入库流水、创建一笔未付款应付账款，并将订单改为“已完成”。如果中途失败，所有变更会回滚。

商品编辑页面只维护商品名称、SKU 和默认价格，不提供库存输入框。商品库存是业务结果，后续只能由入库或出库流程更新。

Windows PowerShell 激活虚拟环境的命令为：

```powershell
.venv\Scripts\Activate.ps1
```

## 数据库说明

运行 `python init_db.py` 后，项目根目录会生成 `database.db`。

初始化脚本是幂等的，重复运行不会重复创建以下演示基础数据：

- 机械键盘，SKU `KB001`，采购价 80，销售价 120，库存 0
- 鼠标，SKU `MS001`，采购价 40，销售价 69，库存 0
- 供应商：南京键盘供应商
- 客户：大圣科技

`Product.stock` 表示当前库存余额，`InventoryTransaction` 表示库存历史流水。当前没有普通页面可以直接修改 `Product.stock`；后续库存变化必须通过采购入库或销售出库业务，同时更新余额和生成流水。

## 测试

```bash
pytest -q
```
