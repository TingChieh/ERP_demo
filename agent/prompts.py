SYSTEM_PROMPT = """
你是企业 ERP 助手，只能使用系统提供的 ERP 工具。

安全规则：
1. 不要执行 SQL，不要直接修改数据库，不要直接修改库存、订单或财务记录。
2. 不要编造商品、SKU、库存、客户、供应商、金额或应收账款。
3. 查询数据必须使用工具返回的真实数据。
4. 商品、客户、供应商不存在时要明确告诉用户，不能自行创建或替换。
5. 存在多个候选实体时必须要求用户确认，不能自行选择。
6. 创建采购订单或销售订单属于写操作，只能调用 prepare 工具生成预览，必须等待用户确认。
7. 当前不支持采购入库、销售出库、客户收款和供应商付款。
8. 信息不足时向用户追问。请使用中文回答。
""".strip()


def _function(name, description, properties, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_product_properties = {
    "product_name": {"type": ["string", "null"]},
    "sku": {"type": ["string", "null"]},
    "quantity": {"type": "integer", "minimum": 1},
    "unit_price": {"type": ["number", "null"], "minimum": 0},
}

TOOL_SCHEMAS = [
    _function(
        "get_inventory",
        "查询一个真实商品的当前库存。可以提供 SKU 或商品名称。",
        {
            "product_name": {"type": ["string", "null"]},
            "sku": {"type": ["string", "null"]},
        },
        ["product_name", "sku"],
    ),
    _function(
        "prepare_purchase_order",
        "解析采购请求并生成采购订单预览，不会创建订单。缺少单价时将使用商品默认采购价。",
        {
            "supplier_name": {"type": "string"},
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": _product_properties,
                    "required": ["product_name", "sku", "quantity", "unit_price"],
                    "additionalProperties": False,
                },
            },
        },
        ["supplier_name", "items"],
    ),
    _function(
        "prepare_sales_order",
        "解析销售请求并生成销售订单预览，不会创建订单。缺少单价时将使用商品默认销售价。",
        {
            "customer_name": {"type": "string"},
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": _product_properties,
                    "required": ["product_name", "sku", "quantity", "unit_price"],
                    "additionalProperties": False,
                },
            },
        },
        ["customer_name", "items"],
    ),
    _function(
        "get_unpaid_receivables",
        "查询全部或指定客户的未收应收账款。",
        {"customer_name": {"type": ["string", "null"]}},
        ["customer_name"],
    ),
]
