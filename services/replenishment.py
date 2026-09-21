from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import ceil

from sqlalchemy import func

from models import (
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    SalesOrder,
    SalesOrderItem,
    db,
)


def get_sales_quantity(product_id, days, as_of=None):
    as_of = as_of or datetime.now(timezone.utc)
    cutoff = as_of - timedelta(days=days)
    quantity = (
        db.session.query(func.coalesce(func.sum(SalesOrderItem.quantity), 0))
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
        .filter(
            SalesOrderItem.product_id == product_id,
            SalesOrder.status == "completed",
            SalesOrder.created_at >= cutoff,
        )
        .scalar()
    )
    return int(quantity or 0)


def get_pending_purchase_quantity(product_id):
    quantity = (
        db.session.query(func.coalesce(func.sum(PurchaseOrderItem.quantity), 0))
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .filter(
            PurchaseOrderItem.product_id == product_id,
            PurchaseOrder.status == "pending_receipt",
        )
        .scalar()
    )
    return int(quantity or 0)


def get_last_purchase_price(product_id):
    item = (
        db.session.query(PurchaseOrderItem)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .filter(PurchaseOrderItem.product_id == product_id)
        .order_by(
            PurchaseOrder.created_at.desc(),
            PurchaseOrder.id.desc(),
            PurchaseOrderItem.id.desc(),
        )
        .first()
    )
    return Decimal(item.unit_price) if item is not None else None


def calculate_days_of_inventory(current_stock, avg_daily_sales_7d):
    average = Decimal(avg_daily_sales_7d)
    if average <= 0:
        return None
    return (Decimal(current_stock) / average).quantize(Decimal("0.01"))


def calculate_recommended_purchase_qty(
    current_stock, pending_purchase_qty, avg_daily_sales_7d, target_days=14
):
    target = (
        Decimal(avg_daily_sales_7d) * Decimal(target_days)
        - Decimal(current_stock)
        - Decimal(pending_purchase_qty)
    )
    return max(0, ceil(target))


def _number(value):
    if value is None:
        return None
    value = Decimal(value)
    return int(value) if value == value.to_integral_value() else float(value)


def _average(sales_quantity, days):
    return (Decimal(sales_quantity) / Decimal(days)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _money(value):
    return f"{Decimal(value):.2f}"


def analyze_replenishment(product_id, as_of=None):
    product = db.session.get(Product, product_id)
    if product is None:
        raise ValueError("商品不存在")

    sales_7d = get_sales_quantity(product_id, 7, as_of=as_of)
    sales_30d = get_sales_quantity(product_id, 30, as_of=as_of)
    avg_7d = _average(sales_7d, 7)
    avg_30d = _average(sales_30d, 30)
    pending = get_pending_purchase_quantity(product_id)
    coverage = calculate_days_of_inventory(product.stock, avg_7d)
    recommended = calculate_recommended_purchase_qty(product.stock, pending, avg_7d)
    default_purchase_price = Decimal(product.purchase_price)
    last_purchase_price = get_last_purchase_price(product_id)
    purchase_price = last_purchase_price or default_purchase_price

    return {
        "product_id": product.id,
        "product_name": product.name,
        "sku": product.sku,
        "current_stock": product.stock,
        "sales_7d": sales_7d,
        "sales_30d": sales_30d,
        "avg_daily_sales_7d": _number(avg_7d),
        "avg_daily_sales_30d": _number(avg_30d),
        "pending_purchase_qty": pending,
        "days_of_inventory": _number(coverage),
        "recommended_purchase_qty": recommended,
        "default_purchase_price": _money(default_purchase_price),
        "last_purchase_price": _money(last_purchase_price) if last_purchase_price else None,
        "purchase_price": _money(purchase_price),
        "low_stock": coverage is not None and coverage < 7,
    }


def get_low_stock_analyses(limit=5, as_of=None):
    analyses = []
    products = Product.query.order_by(Product.name.asc(), Product.id.asc()).all()
    for product in products:
        analysis = analyze_replenishment(product.id, as_of=as_of)
        if analysis["low_stock"]:
            analysis = {"product_id": product.id, **analysis}
            analyses.append(analysis)
    analyses.sort(key=lambda item: (item["days_of_inventory"], item["product_id"]))
    return analyses[:limit]
