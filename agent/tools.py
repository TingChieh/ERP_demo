from decimal import Decimal, InvalidOperation

from models import (
    AccountReceivable,
    Customer,
    Product,
    Supplier,
    db,
)
from services.orders import create_purchase_order_draft, create_sales_order_draft

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
    return message_response(
        f"{product.name}（{product.sku}）当前库存是 {product.stock} 个。",
        data=data,
    )


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
            payload["supplier_id"], payload["items"]
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
        order = create_sales_order_draft(payload["customer_id"], payload["items"])
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
    if not items:
        return message_response("目前没有未收应收账款。", data=data)
    return message_response(
        f"目前共有 {len(items)} 笔未收应收账款，总额 {format_money(total_amount)} 元。",
        data=data,
    )
