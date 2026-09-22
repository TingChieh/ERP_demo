from decimal import Decimal, InvalidOperation

from models import (
    AccountReceivable,
    Customer,
    Product,
    Supplier,
    db,
)
from services.orders import create_purchase_order_draft, create_sales_order_draft
from services.logging import record_database_operation
from services.replenishment import (
    analyze_replenishment,
    get_low_stock_analyses,
)

from .schemas import (
    AgentResponse,
    clarification_response,
    confirmation_response,
    error_response,
    format_money,
    message_response,
)


def _normalize(value):
    return str(value or "").strip().casefold()


def _candidate_product(product):
    return {"id": product.id, "name": product.name, "sku": product.sku}


def _candidate_named(entity):
    return {"id": entity.id, "name": entity.name}


class _ResolutionProblem(Exception):
    def __init__(self, response: AgentResponse):
        self.response = response
        super().__init__(response.message)


def _resolve_product(product_name=None, sku=None):
    if sku and str(sku).strip():
        product = Product.query.filter_by(sku=str(sku).strip()).one_or_none()
        if product is not None:
            return product
        if not product_name:
            raise _ResolutionProblem(
                clarification_response(
                    f"系统中没有找到 SKU“{sku}”对应的商品，请确认 SKU。"
                )
            )

    needle = _normalize(product_name)
    if not needle:
        raise _ResolutionProblem(
            clarification_response("请告诉我商品名称或 SKU。")
        )

    products = Product.query.order_by(Product.name, Product.id).all()
    exact = [product for product in products if _normalize(product.name) == needle]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise _ResolutionProblem(
            clarification_response(
                f"找到多个相关商品，请确认你要选择哪一种“{product_name}”。",
                [_candidate_product(product) for product in exact],
            )
        )

    matches = [product for product in products if needle in _normalize(product.name)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise _ResolutionProblem(
            clarification_response(
                f"找到多个相关商品，请确认你要选择哪一种“{product_name}”。",
                [_candidate_product(product) for product in matches],
            )
        )

    raise _ResolutionProblem(
        clarification_response(
            f"系统中没有找到商品“{product_name}”，请确认商品名称或 SKU。"
        )
    )


def _resolve_named(model, label, value):
    if not value or not str(value).strip():
        raise _ResolutionProblem(clarification_response(f"请告诉我{label}名称。"))

    needle = _normalize(value)
    entities = model.query.order_by(model.name, model.id).all()
    exact = [entity for entity in entities if _normalize(entity.name) == needle]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise _ResolutionProblem(
            clarification_response(
                f"找到多个相关{label}，请确认名称。",
                [_candidate_named(entity) for entity in exact],
            )
        )

    matches = [entity for entity in entities if needle in _normalize(entity.name)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise _ResolutionProblem(
            clarification_response(
                f"找到多个相关{label}，请确认名称。",
                [_candidate_named(entity) for entity in matches],
            )
        )

    raise _ResolutionProblem(
        clarification_response(f"系统中没有找到{label}“{value}”，请确认名称。")
    )


def _parse_quantity(value):
    if value is None or isinstance(value, bool):
        raise ValueError("数量必须是正整数")
    raw = str(value).strip()
    try:
        quantity = int(raw)
    except (TypeError, ValueError):
        raise ValueError("数量必须是正整数") from None
    if quantity <= 0 or str(quantity) != raw:
        raise ValueError("数量必须是正整数")
    return quantity


def _parse_price(value, default):
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal(str(default)), True
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("单价无效") from None
    if not price.is_finite() or price < 0:
        raise ValueError("单价不能小于 0")
    return price, False


def get_inventory(*, product_name=None, sku=None):
    try:
        product = _resolve_product(product_name=product_name, sku=sku)
    except _ResolutionProblem as problem:
        return problem.response

    data = {
        "product_id": product.id,
        "product_name": product.name,
        "sku": product.sku,
        "stock": product.stock,
    }
    record_database_operation(
        source="agent",
        action="get_inventory",
        entity_type="Product",
        entity_id=product.id,
        detail={"sku": product.sku},
    )
    return message_response(
        f"{product.name}（{product.sku}）当前库存是 {product.stock} 个。",
        data=data,
    )


def _format_coverage(days_of_inventory):
    if days_of_inventory is None:
        return "无法计算"
    if isinstance(days_of_inventory, float):
        return f"{days_of_inventory:g}"
    return str(days_of_inventory)


def _replenishment_content(analysis):
    return (
        f"{analysis['product_name']}当前库存 {analysis['current_stock']} 个，"
        f"最近 7 天销售 {analysis['sales_7d']} 个，"
        f"平均每天约销售 {analysis['avg_daily_sales_7d']} 个，"
        f"库存覆盖 {_format_coverage(analysis['days_of_inventory'])} 天，"
        f"待入库 {analysis['pending_purchase_qty']} 个，"
        f"建议采购 {analysis['recommended_purchase_qty']} 个。"
    )


def analyze_low_stock(*, product_name=None):
    try:
        if product_name is None:
            items = get_low_stock_analyses()
            entity_id = "all"
            detail = {"count": len(items), "scope": "low_stock"}
            if not items:
                content = "目前没有库存覆盖少于 7 天的商品。"
            else:
                content = "仅列出库存覆盖少于 7 天的商品：" + "\n".join(
                    _replenishment_content(item) for item in items
                )
        else:
            product = _resolve_product(product_name=product_name)
            items = [analyze_replenishment(product.id)]
            entity_id = product.id
            detail = {"product_id": product.id}
            analysis = items[0]
            if analysis["sales_7d"] == 0:
                content = (
                    f"{product.name}最近 7 天没有销售记录，"
                    "未生成基于销量的补货建议。"
                )
            else:
                content = _replenishment_content(analysis)
    except _ResolutionProblem as problem:
        return problem.response

    record_database_operation(
        source="agent",
        action="analyze_low_stock",
        entity_type="Product",
        entity_id=entity_id,
        detail=detail,
    )
    return message_response(
        content,
        data={"analysis_type": "replenishment", "items": items},
    )


def prepare_replenishment_purchase(
    *, product_name=None, supplier_name=None, quantity=None
):
    try:
        product = _resolve_product(product_name=product_name)
    except _ResolutionProblem as problem:
        return problem.response

    analysis = analyze_replenishment(product.id)
    if analysis["sales_7d"] == 0:
        return message_response(
            f"{product.name}最近 7 天没有销售记录，未创建补货采购预览。"
        )
    if analysis["recommended_purchase_qty"] == 0:
        return message_response(
            f"{product.name}当前库存 {analysis['current_stock']} 个，"
            f"加上待入库 {analysis['pending_purchase_qty']} 个，"
            "已满足 14 天目标库存，不需要补货。"
        )

    product_context = {
        "analysis_type": "replenishment",
        "items": [{"product_name": product.name, "sku": product.sku}],
    }
    try:
        if supplier_name:
            supplier = _resolve_named(Supplier, "供应商", supplier_name)
            supplier_source = "user"
        else:
            suppliers = Supplier.query.order_by(Supplier.name, Supplier.id).all()
            if len(suppliers) != 1:
                return clarification_response(
                    "请确认补货供应商。",
                    [_candidate_named(supplier) for supplier in suppliers],
                    data=product_context,
                )
            supplier = suppliers[0]
            supplier_source = "only_supplier"

        if quantity is None:
            purchase_quantity = analysis["recommended_purchase_qty"]
            quantity_source = "recommendation"
        else:
            purchase_quantity = _parse_quantity(quantity)
            quantity_source = "user"
    except _ResolutionProblem as problem:
        problem.response.data = product_context
        return problem.response
    except ValueError as error:
        return error_response(f"{product.name}{error}。")

    unit_price = Decimal(analysis["purchase_price"])
    subtotal = Decimal(purchase_quantity) * unit_price

    preview = {
        "supplier_name": supplier.name,
        "supplier_source": supplier_source,
        "items": [
            {
                "product_name": product.name,
                "sku": product.sku,
                "quantity": purchase_quantity,
                "unit_price": format_money(unit_price),
                "subtotal": format_money(subtotal),
            }
        ],
        "total_amount": format_money(subtotal),
        "quantity_source": quantity_source,
        "price_source": analysis["price_source"],
        "recommendation": {
            "current_stock": analysis["current_stock"],
            "sales_7d": analysis["sales_7d"],
            "avg_daily_sales_7d": analysis["avg_daily_sales_7d"],
            "days_of_inventory": analysis["days_of_inventory"],
            "coverage": analysis["days_of_inventory"],
            "pending_purchase_qty": analysis["pending_purchase_qty"],
            "target_days": 14,
            "recommended_purchase_qty": analysis["recommended_purchase_qty"],
        },
    }
    payload = {
        "supplier_id": supplier.id,
        "items": [
            {
                "product_id": product.id,
                "quantity": purchase_quantity,
                "unit_price": format_money(unit_price),
            }
        ],
    }
    return confirmation_response("create_purchase_order", preview, payload)


def _prepare_order(*, party_model, party_label, party_name, items, price_field, action):
    try:
        party = _resolve_named(party_model, party_label, party_name)
    except _ResolutionProblem as problem:
        return problem.response

    if not isinstance(items, list) or not items:
        return clarification_response("请至少提供一个商品明细。")

    preview_items = []
    payload_items = []
    product_ids = set()
    total_amount = Decimal("0")

    for raw_item in items:
        if not isinstance(raw_item, dict):
            return error_response("商品明细格式无效。")
        try:
            product = _resolve_product(
                product_name=raw_item.get("product_name"),
                sku=raw_item.get("sku"),
            )
            quantity = _parse_quantity(raw_item.get("quantity"))
            price, is_default = _parse_price(
                raw_item.get("unit_price"), getattr(product, price_field)
            )
        except _ResolutionProblem as problem:
            return problem.response
        except ValueError as error:
            return error_response(f"{product.name if 'product' in locals() else '商品'}{error}。")

        if product.id in product_ids:
            return error_response("同一个订单不能重复添加同一商品。")
        product_ids.add(product.id)

        subtotal = Decimal(quantity) * price
        total_amount += subtotal
        preview_items.append(
            {
                "product_name": product.name,
                "sku": product.sku,
                "quantity": quantity,
                "unit_price": format_money(price),
                "subtotal": format_money(subtotal),
                "price_source": (
                    f"default_{'purchase' if price_field == 'purchase_price' else 'sale'}_price"
                    if is_default
                    else "user"
                ),
            }
        )
        payload_items.append(
            {
                "product_id": product.id,
                "quantity": quantity,
                "unit_price": format_money(price),
            }
        )

    preview = {
        f"{('supplier' if party_model is Supplier else 'customer')}_name": party.name,
        "items": preview_items,
        "total_amount": format_money(total_amount),
    }
    payload = {
        "party_id": party.id,
        "items": payload_items,
    }
    if party_model is Supplier:
        payload["supplier_id"] = payload.pop("party_id")
    else:
        payload["customer_id"] = payload.pop("party_id")
    return confirmation_response(action, preview, payload)


def prepare_purchase_order(*, supplier_name=None, items=None, total_amount=None):
    del total_amount
    return _prepare_order(
        party_model=Supplier,
        party_label="供应商",
        party_name=supplier_name,
        items=items,
        price_field="purchase_price",
        action="create_purchase_order",
    )


def prepare_sales_order(*, customer_name=None, items=None, total_amount=None):
    del total_amount
    return _prepare_order(
        party_model=Customer,
        party_label="客户",
        party_name=customer_name,
        items=items,
        price_field="sale_price",
        action="create_sales_order",
    )


def confirm_purchase_order(payload):
    if not isinstance(payload, dict):
        return error_response("采购订单确认数据无效。")
    try:
        order = create_purchase_order_draft(
            payload["supplier_id"], payload["items"], source="agent"
        )
    except (KeyError, TypeError, ValueError):
        return error_response("采购订单确认数据无效，未创建订单。")
    except Exception:
        db.session.rollback()
        return error_response("采购订单保存失败，未创建订单。")
    return message_response(
        f"采购订单 {order.order_no} 已创建为草稿。",
        data={"order_id": order.id, "order_no": order.order_no},
    )


def confirm_sales_order(payload):
    if not isinstance(payload, dict):
        return error_response("销售订单确认数据无效。")
    try:
        order = create_sales_order_draft(
            payload["customer_id"], payload["items"], source="agent"
        )
    except (KeyError, TypeError, ValueError):
        return error_response("销售订单确认数据无效，未创建订单。")
    except Exception:
        db.session.rollback()
        return error_response("销售订单保存失败，未创建订单。")
    return message_response(
        f"销售订单 {order.order_no} 已创建为草稿。",
        data={"order_id": order.id, "order_no": order.order_no},
    )


def get_unpaid_receivables(*, customer_name=None):
    if customer_name:
        try:
            customer = _resolve_named(Customer, "客户", customer_name)
        except _ResolutionProblem as problem:
            return problem.response
        receivables = (
            AccountReceivable.query.filter_by(
                customer_id=customer.id, status="unpaid"
            )
            .order_by(AccountReceivable.id.desc())
            .all()
        )
    else:
        receivables = (
            AccountReceivable.query.filter_by(status="unpaid")
            .order_by(AccountReceivable.id.desc())
            .all()
        )

    items = [
        {
            "sales_order_no": receivable.sales_order.order_no,
            "customer": receivable.customer.name,
            "amount": format_money(receivable.amount),
            "created_at": receivable.created_at.isoformat(),
        }
        for receivable in receivables
    ]
    total_amount = sum(
        (Decimal(str(receivable.amount)) for receivable in receivables),
        Decimal("0"),
    )
    data = {"total_amount": format_money(total_amount), "items": items}
    record_database_operation(
        source="agent",
        action="get_unpaid_receivables",
        entity_type="AccountReceivable",
        entity_id=(customer.id if customer_name else "all"),
        detail={"count": len(items), "total_amount": format_money(total_amount)},
    )
    if not items:
        return message_response("目前没有未收应收账款。", data=data)
    return message_response(
        f"目前共有 {len(items)} 笔未收应收账款，总额 {format_money(total_amount)} 元。",
        data=data,
    )
