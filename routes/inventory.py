from flask import Blueprint, render_template

from models import InventoryTransaction, Product, PurchaseOrder, SalesOrder


inventory_bp = Blueprint("inventory", __name__)

PURCHASE_RECEIPT_STATUS_LABELS = {"pending_receipt": "待入库"}
SALES_SHIPMENT_STATUS_LABELS = {"pending_shipment": "待出库"}
INVENTORY_TRANSACTION_TYPE_LABELS = {"inbound": "入库", "outbound": "出库"}


@inventory_bp.get("/purchase-receipts")
def purchase_receipts():
    orders = PurchaseOrder.query.filter_by(status="pending_receipt").order_by(
        PurchaseOrder.id.desc()
    ).all()
    return render_template(
        "inventory/purchase_receipts.html",
        orders=orders,
        status_labels=PURCHASE_RECEIPT_STATUS_LABELS,
    )


@inventory_bp.get("/sales-shipments")
def sales_shipments():
    orders = SalesOrder.query.filter_by(status="pending_shipment").order_by(
        SalesOrder.id.desc()
    ).all()
    return render_template(
        "inventory/sales_shipments.html",
        orders=orders,
        status_labels=SALES_SHIPMENT_STATUS_LABELS,
    )


@inventory_bp.get("/inventory")
def current_inventory():
    products = Product.query.order_by(Product.name, Product.id).all()
    return render_template("inventory/current.html", products=products)


@inventory_bp.get("/inventory/transactions")
def inventory_transactions():
    transactions = InventoryTransaction.query.order_by(
        InventoryTransaction.id.desc()
    ).all()
    return render_template(
        "inventory/transactions.html",
        transactions=transactions,
        type_labels=INVENTORY_TRANSACTION_TYPE_LABELS,
    )
