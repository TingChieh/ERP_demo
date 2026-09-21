from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def utc_now():
    return datetime.now(timezone.utc)


class Product(db.Model):
    __tablename__ = "product"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(50), nullable=False, unique=True)
    purchase_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    sale_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)

    # Product.stock is the fast current-balance field. It must only be changed
    # by future receipt/shipment workflows together with an inventory record;
    # this skeleton intentionally exposes no ordinary stock-edit operation.
    stock = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.CheckConstraint("stock >= 0", name="ck_product_stock_non_negative"),
    )

    purchase_items = db.relationship("PurchaseOrderItem", back_populates="product")
    sales_items = db.relationship("SalesOrderItem", back_populates="product")
    inventory_transactions = db.relationship(
        "InventoryTransaction", back_populates="product"
    )


class Supplier(db.Model):
    __tablename__ = "supplier"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=False, default="")

    purchase_orders = db.relationship("PurchaseOrder", back_populates="supplier")


class Customer(db.Model):
    __tablename__ = "customer"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=False, default="")

    sales_orders = db.relationship("SalesOrder", back_populates="customer")


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_order"

    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(50), nullable=False, unique=True)
    supplier_id = db.Column(
        db.Integer, db.ForeignKey("supplier.id"), nullable=False
    )
    status = db.Column(db.String(30), nullable=False, default="draft")
    total_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'pending_receipt', 'completed')",
            name="ck_purchase_order_status",
        ),
    )

    supplier = db.relationship("Supplier", back_populates="purchase_orders")
    items = db.relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )
    payable = db.relationship(
        "AccountPayable", back_populates="purchase_order", uselist=False
    )


class PurchaseOrderItem(db.Model):
    __tablename__ = "purchase_order_item"

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(
        db.Integer, db.ForeignKey("purchase_order.id"), nullable=False
    )
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_purchase_item_quantity_positive"),
        db.UniqueConstraint(
            "purchase_order_id", "product_id", name="uq_purchase_order_product"
        ),
    )

    purchase_order = db.relationship("PurchaseOrder", back_populates="items")
    product = db.relationship("Product", back_populates="purchase_items")


class SalesOrder(db.Model):
    __tablename__ = "sales_order"

    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(50), nullable=False, unique=True)
    customer_id = db.Column(
        db.Integer, db.ForeignKey("customer.id"), nullable=False
    )
    status = db.Column(db.String(30), nullable=False, default="draft")
    total_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'pending_shipment', 'completed')",
            name="ck_sales_order_status",
        ),
    )

    customer = db.relationship("Customer", back_populates="sales_orders")
    items = db.relationship(
        "SalesOrderItem",
        back_populates="sales_order",
        cascade="all, delete-orphan",
    )
    receivable = db.relationship(
        "AccountReceivable", back_populates="sales_order", uselist=False
    )


class SalesOrderItem(db.Model):
    __tablename__ = "sales_order_item"

    id = db.Column(db.Integer, primary_key=True)
    sales_order_id = db.Column(
        db.Integer, db.ForeignKey("sales_order.id"), nullable=False
    )
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_sales_item_quantity_positive"),
        db.UniqueConstraint(
            "sales_order_id", "product_id", name="uq_sales_order_product"
        ),
    )

    sales_order = db.relationship("SalesOrder", back_populates="items")
    product = db.relationship("Product", back_populates="sales_items")


class InventoryTransaction(db.Model):
    __tablename__ = "inventory_transaction"

    # This table is an append-only history. Future receipt/shipment workflows
    # must update Product.stock and create this row in the same transaction;
    # there is deliberately no ordinary page for editing either value alone.
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    related_order_no = db.Column(db.String(50), nullable=False)
    balance_after = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    __table_args__ = (
        db.CheckConstraint(
            "type IN ('inbound', 'outbound')", name="ck_inventory_transaction_type"
        ),
        db.CheckConstraint(
            "quantity > 0", name="ck_inventory_transaction_quantity_positive"
        ),
        db.CheckConstraint(
            "balance_after >= 0", name="ck_inventory_balance_after_non_negative"
        ),
    )

    product = db.relationship("Product", back_populates="inventory_transactions")


class AccountReceivable(db.Model):
    __tablename__ = "account_receivable"

    id = db.Column(db.Integer, primary_key=True)
    sales_order_id = db.Column(
        db.Integer, db.ForeignKey("sales_order.id"), nullable=False, unique=True
    )
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="unpaid")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    paid_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('unpaid', 'paid')", name="ck_receivable_status"
        ),
    )

    sales_order = db.relationship("SalesOrder", back_populates="receivable")
    customer = db.relationship("Customer")


class AccountPayable(db.Model):
    __tablename__ = "account_payable"

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(
        db.Integer, db.ForeignKey("purchase_order.id"), nullable=False, unique=True
    )
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="unpaid")
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    paid_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.CheckConstraint("status IN ('unpaid', 'paid')", name="ck_payable_status"),
    )

    purchase_order = db.relationship("PurchaseOrder", back_populates="payable")
    supplier = db.relationship("Supplier")
