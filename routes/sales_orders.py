from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import Blueprint, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from models import (
    AccountReceivable,
    Customer,
    InventoryTransaction,
    Product,
    SalesOrder,
    SalesOrderItem,
    db,
)


sales_orders_bp = Blueprint("sales_orders", __name__, url_prefix="/sales-orders")

STATUS_LABELS = {
    "draft": "草稿",
    "pending_shipment": "待出库",
    "completed": "已完成",
}

RECEIVABLE_STATUS_LABELS = {
    "unpaid": "未收款",
    "paid": "已收款",
}


def _empty_form_data(products):
    return {
        "customer_id": "",
        "selected_product_ids": [],
        "quantities": {},
        "unit_prices": {str(product.id): str(product.sale_price) for product in products},
    }


def _read_form_data(request_form):
    selected_product_ids = request_form.getlist("product_ids")
    quantities = {}
    unit_prices = {}
    for product_id in selected_product_ids:
        quantities[product_id] = request_form.get(f"quantity_{product_id}", "").strip()
        unit_prices[product_id] = request_form.get(
            f"unit_price_{product_id}", ""
        ).strip()

    return {
        "customer_id": request_form.get("customer_id", "").strip(),
        "selected_product_ids": selected_product_ids,
        "quantities": quantities,
        "unit_prices": unit_prices,
    }


def _generate_order_no():
    """Generate a simple unique SO number for this single-application demo."""
    prefix = f"SO{datetime.now(timezone.utc):%Y%m%d}"
    latest = (
        SalesOrder.query.filter(SalesOrder.order_no.like(f"{prefix}%"))
        .order_by(SalesOrder.order_no.desc())
        .first()
    )

    next_number = 1
    if latest:
        suffix = latest.order_no[len(prefix) :]
        if suffix.isdigit():
            next_number = int(suffix) + 1

    while True:
        candidate = f"{prefix}{next_number:03d}"
        if SalesOrder.query.filter_by(order_no=candidate).first() is None:
            return candidate
        next_number += 1


def _validate_form(form_data):
    errors = []
    lines = []
    total_amount = Decimal("0")

    customer_id = None
    if not form_data["customer_id"]:
        errors.append("请选择客户")
    else:
        try:
            customer_id = int(form_data["customer_id"])
        except ValueError:
            errors.append("客户无效")
        else:
            if db.session.get(Customer, customer_id) is None:
                errors.append("客户不存在")

    selected_product_ids = form_data["selected_product_ids"]
    if not selected_product_ids:
        errors.append("至少选择一个商品")
    elif len(selected_product_ids) != len(set(selected_product_ids)):
        errors.append("同一个商品不能重复添加")

    for raw_product_id in selected_product_ids:
        try:
            product_id = int(raw_product_id)
        except ValueError:
            errors.append("商品无效")
            continue

        product = db.session.get(Product, product_id)
        if product is None:
            errors.append("商品不存在")
            continue

        raw_quantity = form_data["quantities"].get(raw_product_id, "")
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            errors.append(f"{product.name}的数量必须是正整数")
            continue
        if quantity <= 0:
            errors.append(f"{product.name}的数量必须大于 0")
            continue

        raw_unit_price = form_data["unit_prices"].get(raw_product_id, "")
        try:
            unit_price = Decimal(raw_unit_price)
        except (InvalidOperation, TypeError, ValueError):
            errors.append(f"{product.name}的销售单价无效")
            continue
        if not unit_price.is_finite() or unit_price < 0:
            errors.append(f"{product.name}的销售单价不能小于 0")
            continue

        lines.append(
            {
                "product": product,
                "quantity": quantity,
                "unit_price": unit_price,
            }
        )
        total_amount += Decimal(quantity) * unit_price

    return errors, customer_id, lines, total_amount


@sales_orders_bp.get("/", strict_slashes=False)
def list_sales_orders():
    orders = SalesOrder.query.order_by(SalesOrder.id.desc()).all()
    return render_template(
        "sales_orders/list.html",
        orders=orders,
        status_labels=STATUS_LABELS,
    )


@sales_orders_bp.route("/new", methods=["GET", "POST"])
def new_sales_order():
    customers = Customer.query.order_by(Customer.name).all()
    products = Product.query.order_by(Product.name).all()
    form_data = _empty_form_data(products)
    errors = []

    if request.method == "POST":
        form_data = _read_form_data(request.form)
        errors, customer_id, lines, total_amount = _validate_form(form_data)
        if not errors:
            # A sales order records customer demand and a price snapshot. It
            # does not mean goods have shipped, so this step must not inspect,
            # reserve, or decrease Product.stock.
            order = SalesOrder(
                order_no=_generate_order_no(),
                customer_id=customer_id,
                status="draft",
                total_amount=total_amount,
            )

            try:
                # One commit covers the order and every line. A failure rolls
                # back the whole sales order instead of leaving partial lines.
                db.session.add(order)
                for line in lines:
                    db.session.add(
                        SalesOrderItem(
                            sales_order=order,
                            product_id=line["product"].id,
                            quantity=line["quantity"],
                            unit_price=line["unit_price"],
                        )
                    )
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                errors.append("销售订单保存失败，请检查数据后重试")
            else:
                return redirect(
                    url_for("sales_orders.sales_order_detail", order_id=order.id)
                )

    return render_template(
        "sales_orders/form.html",
        customers=customers,
        products=products,
        form_data=form_data,
        errors=errors,
    )


@sales_orders_bp.get("/<int:order_id>")
def sales_order_detail(order_id):
    order = db.get_or_404(SalesOrder, order_id)
    return _render_sales_order_detail(order)


def _render_sales_order_detail(order, error=None):
    inventory_transactions = (
        InventoryTransaction.query.filter_by(
            related_order_no=order.order_no, type="outbound"
        )
        .order_by(InventoryTransaction.id)
        .all()
    )
    return render_template(
        "sales_orders/detail.html",
        order=order,
        status_labels=STATUS_LABELS,
        receivable_status_labels=RECEIVABLE_STATUS_LABELS,
        inventory_transactions=inventory_transactions,
        error=error,
    )


@sales_orders_bp.post("/<int:order_id>/submit")
def submit_sales_order(order_id):
    order = db.get_or_404(SalesOrder, order_id)
    if order.status != "draft":
        return (
            _render_sales_order_detail(
                order, error="只有草稿状态的销售订单可以提交"
            ),
            400,
        )

    # Submission confirms the sales request internally, but shipment is a
    # separate warehouse event and is intentionally not performed here.
    order.status = "pending_shipment"
    db.session.commit()
    return redirect(url_for("sales_orders.sales_order_detail", order_id=order.id))


@sales_orders_bp.post("/<int:order_id>/ship")
def ship_sales_order(order_id):
    order = db.get_or_404(SalesOrder, order_id)

    if order.status != "pending_shipment":
        return (
            _render_sales_order_detail(
                order, error="只有待出库状态的销售订单可以确认出库"
            ),
            400,
        )

    if order.receivable is not None:
        return (
            _render_sales_order_detail(
                order, error="该销售订单已经存在应收账款，不能重复出库"
            ),
            400,
        )

    if not order.items:
        return (
            _render_sales_order_detail(order, error="销售订单没有商品明细，不能出库"),
            400,
        )

    # SQLite is sufficient for this learning demo, but this read-then-write
    # check is not a production concurrency lock. Real ERP systems may use
    # row locks, atomic UPDATE, or optimistic versioning to prevent oversell.
    insufficient_items = [
        item
        for item in order.items
        if item.product.stock < item.quantity
    ]
    if insufficient_items:
        # The validation happens before any stock write, so an order with one
        # insufficient line cannot partially ship its other lines.
        return (
            _render_sales_order_detail(order, error="库存不足，无法出库"),
            400,
        )

    try:
        for item in order.items:
            product = item.product
            product.stock -= item.quantity
            db.session.add(
                InventoryTransaction(
                    product_id=product.id,
                    type="outbound",
                    quantity=item.quantity,
                    related_order_no=order.order_no,
                    balance_after=product.stock,
                )
            )

        # The receivable is created only after physical shipment is staged,
        # and uses the confirmed order total rather than Product.sale_price.
        db.session.add(
            AccountReceivable(
                sales_order_id=order.id,
                customer_id=order.customer_id,
                amount=order.total_amount,
                status="unpaid",
            )
        )
        order.status = "completed"
        db.session.commit()
    except Exception:
        # If a later line or financial insert fails, restore every earlier
        # stock decrement, transaction row, receivable, and status change.
        db.session.rollback()
        order = db.session.get(SalesOrder, order_id)
        return (
            _render_sales_order_detail(order, error="出库失败，系统已回滚全部变更"),
            500,
        )

    return redirect(url_for("sales_orders.sales_order_detail", order_id=order.id))
