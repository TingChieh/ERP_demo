from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import SQLAlchemyError

from models import (
    Customer,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    SalesOrder,
    SalesOrderItem,
    Supplier,
    db,
)


def _parse_quantity(value):
    if isinstance(value, bool):
        raise ValueError("数量必须是正整数")
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        raise ValueError("数量必须是正整数") from None
    if quantity <= 0 or str(value).strip() != str(quantity):
        raise ValueError("数量必须是正整数")
    return quantity


def _parse_unit_price(value):
    try:
        unit_price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("单价无效") from None
    if not unit_price.is_finite() or unit_price < 0:
        raise ValueError("单价不能小于 0")
    return unit_price


def _normalize_lines(lines):
    if not lines:
        raise ValueError("至少需要一个商品")

    normalized = []
    product_ids = set()
    for raw_line in lines:
        if not isinstance(raw_line, dict):
            raise ValueError("商品明细无效")

        try:
            product_id = int(raw_line["product_id"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("商品无效") from None

        quantity = _parse_quantity(raw_line.get("quantity"))
        unit_price = _parse_unit_price(raw_line.get("unit_price"))
        product = db.session.get(Product, product_id)
        if product is None:
            raise ValueError("商品不存在")
        if product_id in product_ids:
            raise ValueError("同一个商品不能重复添加")

        product_ids.add(product_id)
        normalized.append(
            {
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": unit_price,
            }
        )

    return normalized


def _next_order_no(model, prefix):
    date_prefix = f"{prefix}{datetime.now(timezone.utc):%Y%m%d}"
    latest = (
        model.query.filter(model.order_no.like(f"{date_prefix}%"))
        .order_by(model.order_no.desc())
        .first()
    )

    next_number = 1
    if latest:
        suffix = latest.order_no[len(date_prefix) :]
        if suffix.isdigit():
            next_number = int(suffix) + 1

    while True:
        candidate = f"{date_prefix}{next_number:03d}"
        if model.query.filter_by(order_no=candidate).first() is None:
            return candidate
        next_number += 1


def create_purchase_order_draft(supplier_id, lines):
    supplier = db.session.get(Supplier, supplier_id)
    if supplier is None:
        raise ValueError("供应商不存在")
    normalized_lines = _normalize_lines(lines)
    total_amount = sum(
        (
            Decimal(line["quantity"]) * line["unit_price"]
            for line in normalized_lines
        ),
        Decimal("0"),
    )
    order = PurchaseOrder(
        order_no=_next_order_no(PurchaseOrder, "PO"),
        supplier_id=supplier.id,
        status="draft",
        total_amount=total_amount,
    )

    try:
        db.session.add(order)
        for line in normalized_lines:
            db.session.add(
                PurchaseOrderItem(
                    purchase_order=order,
                    product_id=line["product_id"],
                    quantity=line["quantity"],
                    unit_price=line["unit_price"],
                )
            )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise

    return order


def create_sales_order_draft(customer_id, lines):
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        raise ValueError("客户不存在")
    normalized_lines = _normalize_lines(lines)
    total_amount = sum(
        (
            Decimal(line["quantity"]) * line["unit_price"]
            for line in normalized_lines
        ),
        Decimal("0"),
    )
    order = SalesOrder(
        order_no=_next_order_no(SalesOrder, "SO"),
        customer_id=customer.id,
        status="draft",
        total_amount=total_amount,
    )

    try:
        db.session.add(order)
        for line in normalized_lines:
            db.session.add(
                SalesOrderItem(
                    sales_order=order,
                    product_id=line["product_id"],
                    quantity=line["quantity"],
                    unit_price=line["unit_price"],
                )
            )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise

    return order
