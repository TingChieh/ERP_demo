from decimal import Decimal, InvalidOperation

from flask import Blueprint, redirect, render_template, request, url_for
from sqlalchemy.exc import SQLAlchemyError

from models import (
    AccountPayable,
    InventoryTransaction,
    Product,
    PurchaseOrder,
    Supplier,
    db,
)
from services.orders import create_purchase_order_draft


purchase_orders_bp = Blueprint(
    "purchase_orders", __name__, url_prefix="/purchase-orders"
)

STATUS_LABELS = {
    "draft": "草稿",
    "pending_receipt": "待入库",
    "completed": "已完成",
}

PAYABLE_STATUS_LABELS = {
    "unpaid": "未付款",
    "paid": "已付款",
}


def _empty_form_data(products):
    return {
        "supplier_id": "",
        "selected_product_ids": [],
        "quantities": {},
        "unit_prices": {str(product.id): str(product.purchase_price) for product in products},
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
        "supplier_id": request_form.get("supplier_id", "").strip(),
        "selected_product_ids": selected_product_ids,
        "quantities": quantities,
        "unit_prices": unit_prices,
    }


def _validate_form(form_data):
    errors = []
    lines = []
    total_amount = Decimal("0")

    supplier_id = None
    if not form_data["supplier_id"]:
        errors.append("请选择供应商")
    else:
        try:
            supplier_id = int(form_data["supplier_id"])
        except ValueError:
            errors.append("供应商无效")
        else:
            if db.session.get(Supplier, supplier_id) is None:
                errors.append("供应商不存在")

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
            errors.append(f"{product.name}的采购单价无效")
            continue
        if not unit_price.is_finite() or unit_price < 0:
            errors.append(f"{product.name}的采购单价不能小于 0")
            continue

        lines.append(
            {
                "product": product,
                "quantity": quantity,
                "unit_price": unit_price,
            }
        )
        total_amount += Decimal(quantity) * unit_price

    return errors, supplier_id, lines, total_amount


@purchase_orders_bp.get("/", strict_slashes=False)
def list_purchase_orders():
    orders = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).all()
    return render_template(
        "purchase_orders/list.html",
        orders=orders,
        status_labels=STATUS_LABELS,
    )


@purchase_orders_bp.route("/new", methods=["GET", "POST"])
def new_purchase_order():
    suppliers = Supplier.query.order_by(Supplier.name).all()
    products = Product.query.order_by(Product.name).all()
    form_data = _empty_form_data(products)
    errors = []

    if request.method == "POST":
        form_data = _read_form_data(request.form)
        errors, supplier_id, lines, total_amount = _validate_form(form_data)
        if not errors:
            try:
                order = create_purchase_order_draft(
                    supplier_id,
                    [
                        {
                            "product_id": line["product"].id,
                            "quantity": line["quantity"],
                            "unit_price": line["unit_price"],
                        }
                        for line in lines
                    ],
                )
            except (SQLAlchemyError, ValueError):
                db.session.rollback()
                errors.append("采购订单保存失败，请检查数据后重试")
            else:
                return redirect(
                    url_for("purchase_orders.purchase_order_detail", order_id=order.id)
                )

    return render_template(
        "purchase_orders/form.html",
        suppliers=suppliers,
        products=products,
        form_data=form_data,
        errors=errors,
    )


@purchase_orders_bp.get("/<int:order_id>")
def purchase_order_detail(order_id):
    order = db.get_or_404(PurchaseOrder, order_id)
    return _render_purchase_order_detail(order)


def _render_purchase_order_detail(order, error=None):
    inventory_transactions = (
        InventoryTransaction.query.filter_by(
            related_order_no=order.order_no, type="inbound"
        )
        .order_by(InventoryTransaction.id)
        .all()
    )
    return render_template(
        "purchase_orders/detail.html",
        order=order,
        status_labels=STATUS_LABELS,
        payable_status_labels=PAYABLE_STATUS_LABELS,
        inventory_transactions=inventory_transactions,
        error=error,
    )


@purchase_orders_bp.post("/<int:order_id>/submit")
def submit_purchase_order(order_id):
    order = db.get_or_404(PurchaseOrder, order_id)
    if order.status != "draft":
        return (
            _render_purchase_order_detail(
                order, error="只有草稿状态的采购订单可以提交"
            ),
            400,
        )

    # Submission confirms the purchasing request internally, but warehouse
    # receipt is a separate physical event and is intentionally not performed
    # by this route.
    order.status = "pending_receipt"
    db.session.commit()
    return redirect(
        url_for("purchase_orders.purchase_order_detail", order_id=order.id)
    )


@purchase_orders_bp.post("/<int:order_id>/receive")
def receive_purchase_order(order_id):
    order = db.get_or_404(PurchaseOrder, order_id)

    if order.status != "pending_receipt":
        return (
            _render_purchase_order_detail(
                order, error="只有待入库状态的采购订单可以确认入库"
            ),
            400,
        )

    if order.payable is not None:
        return (
            _render_purchase_order_detail(
                order, error="该采购订单已经存在应付账款，不能重复入库"
            ),
            400,
        )

    if not order.items:
        return (
            _render_purchase_order_detail(order, error="采购订单没有商品明细，不能入库"),
            400,
        )

    try:
        # Receipt is the physical event that changes inventory. All product
        # balances, inbound history, payable creation, and order completion
        # stay in one database transaction so partial receipt is impossible.
        for item in order.items:
            product = item.product
            product.stock += item.quantity
            db.session.add(
                InventoryTransaction(
                    product_id=product.id,
                    type="inbound",
                    quantity=item.quantity,
                    related_order_no=order.order_no,
                    balance_after=product.stock,
                )
            )

        # The payable uses the confirmed order total, not today's product
        # default price. This preserves the historical purchase amount.
        db.session.add(
            AccountPayable(
                purchase_order_id=order.id,
                supplier_id=order.supplier_id,
                amount=order.total_amount,
                status="unpaid",
            )
        )
        order.status = "completed"
        db.session.commit()
    except Exception:
        # A failure in any item, transaction, payable, or status update rolls
        # back every staged change, including earlier stock increments.
        db.session.rollback()
        order = db.session.get(PurchaseOrder, order_id)
        return (
            _render_purchase_order_detail(order, error="入库失败，系统已回滚全部变更"),
            500,
        )

    return redirect(
        url_for("purchase_orders.purchase_order_detail", order_id=order.id)
    )
