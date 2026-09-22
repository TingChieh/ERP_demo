from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import event

from agent.tools import analyze_low_stock, prepare_replenishment_purchase
from app import create_app
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


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'replenishment_agent.db'}",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def replenishment_data(app):
    with app.app_context():
        supplier = Supplier(name="南京键盘供应商", phone="")
        customer = Customer(name="大圣科技", phone="")
        product = Product(
            name="机械键盘",
            sku="KB001",
            purchase_price=80,
            sale_price=120,
            stock=20,
        )
        db.session.add_all([supplier, customer, product])
        db.session.flush()

        sales_order = SalesOrder(
            order_no="SO-REPLENISHMENT",
            customer_id=customer.id,
            status="completed",
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        sales_order.items.append(
            SalesOrderItem(product_id=product.id, quantity=35, unit_price=120)
        )
        pending_purchase = PurchaseOrder(
            order_no="PO-PENDING-REPLENISHMENT",
            supplier_id=supplier.id,
            status="pending_receipt",
        )
        pending_purchase.items.append(
            PurchaseOrderItem(product_id=product.id, quantity=10, unit_price=78)
        )
        db.session.add_all([sales_order, pending_purchase])
        db.session.commit()
        return {"product_id": product.id, "supplier_id": supplier.id}


def test_analyze_low_stock_returns_real_metrics(app, replenishment_data):
    with app.app_context():
        response = analyze_low_stock(product_name="机械键盘")

        assert response.type == "message"
        assert response.data["items"][0]["current_stock"] == 20
        assert response.data["items"][0]["sales_7d"] == 35
        assert response.data["items"][0]["recommended_purchase_qty"] == 40
        assert "覆盖" in response.content
        assert "平均每天约销售 5 个" in response.content
        assert "待入库" in response.content


def test_analyze_low_stock_does_not_fabricate_unknown_product(app, replenishment_data):
    with app.app_context():
        response = analyze_low_stock(product_name="不存在的商品")

        assert response.type == "clarification"
        assert response.data is None


def test_replenishment_preview_uses_backend_recommendation_and_last_price(
    app, replenishment_data
):
    with app.app_context():
        response = prepare_replenishment_purchase(
            product_name="机械键盘", supplier_name="南京键盘供应商"
        )

        assert response.type == "confirmation"
        assert response.action == "create_purchase_order"
        assert response.preview["items"][0]["quantity"] == 40
        assert response.preview["items"][0]["unit_price"] == "78.00"
        assert response.preview["recommendation"]["days_of_inventory"] == 4
        assert response.preview["recommendation"]["coverage"] == 4
        assert PurchaseOrder.query.count() == 1


def test_replenishment_preview_requires_supplier_when_multiple_suppliers_exist(
    app, replenishment_data
):
    with app.app_context():
        db.session.add(Supplier(name="另一供应商", phone=""))
        db.session.commit()

        response = prepare_replenishment_purchase(product_name="机械键盘")

        assert response.type == "clarification"
        assert len(response.candidates) == 2
        assert PurchaseOrder.query.count() == 1


@pytest.mark.parametrize(
    "history_price,price,source,total",
    [
        (78, "78.00", "last_purchase_price", "3120.00"),
        (0, "0.00", "last_purchase_price", "0.00"),
        (None, "80.00", "product_purchase_price", "4000.00"),
    ],
)
def test_preview_resolves_purchase_price_once(
    app, replenishment_data, history_price, price, source, total
):
    with app.app_context():
        purchase = PurchaseOrder.query.one()
        if history_price is None:
            db.session.delete(purchase)
        else:
            purchase.items[0].unit_price = history_price
        db.session.commit()
        orders_before = PurchaseOrder.query.count()
        price_queries = []

        def record_price_query(conn, cursor, statement, parameters, context, executemany):
            if "FROM purchase_order_item" in statement and "ORDER BY" in statement:
                price_queries.append(statement)

        event.listen(db.engine, "before_cursor_execute", record_price_query)
        try:
            response = prepare_replenishment_purchase(product_name="机械键盘")
        finally:
            event.remove(db.engine, "before_cursor_execute", record_price_query)

        assert response.type == "confirmation"
        assert response.preview["items"][0]["unit_price"] == price
        assert response.payload["items"][0]["unit_price"] == price
        assert response.preview["total_amount"] == total
        assert response.preview["price_source"] == source
        assert len(price_queries) == 1
        assert PurchaseOrder.query.count() == orders_before


def test_single_supplier_can_be_defaulted_and_explicit_quantity_is_shown(
    app, replenishment_data
):
    with app.app_context():
        response = prepare_replenishment_purchase(product_name="机械键盘", quantity=40)

        assert response.type == "confirmation"
        assert response.preview["supplier_name"] == "南京键盘供应商"
        assert response.preview["quantity_source"] == "user"


def test_no_sales_product_returns_message_without_creating_order(app, replenishment_data):
    with app.app_context():
        db.session.add(
            Product(
                name="无销售键盘",
                sku="KB-NO-SALES",
                purchase_price=60,
                sale_price=90,
                stock=0,
            )
        )
        db.session.commit()
        orders_before = PurchaseOrder.query.count()

        response = prepare_replenishment_purchase(product_name="无销售键盘")

        assert response.type == "message"
        assert "最近 7 天没有销售记录" in response.content
        assert PurchaseOrder.query.count() == orders_before


def test_sufficient_pending_receipt_returns_message_without_creating_order(
    app, replenishment_data
):
    with app.app_context():
        product = Product(
            name="待入库充足键盘",
            sku="KB-SUFFICIENT",
            purchase_price=60,
            sale_price=90,
            stock=5,
        )
        customer = Customer.query.one()
        supplier = Supplier.query.one()
        db.session.add(product)
        db.session.flush()
        sales_order = SalesOrder(
            order_no="SO-SUFFICIENT",
            customer_id=customer.id,
            status="completed",
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        sales_order.items.append(
            SalesOrderItem(product_id=product.id, quantity=35, unit_price=90)
        )
        pending_purchase = PurchaseOrder(
            order_no="PO-SUFFICIENT",
            supplier_id=supplier.id,
            status="pending_receipt",
        )
        pending_purchase.items.append(
            PurchaseOrderItem(product_id=product.id, quantity=100, unit_price=60)
        )
        db.session.add_all([sales_order, pending_purchase])
        db.session.commit()
        orders_before = PurchaseOrder.query.count()

        response = prepare_replenishment_purchase(product_name="待入库充足键盘")

        assert response.type == "message"
        assert "不需要补货" in response.content
        assert PurchaseOrder.query.count() == orders_before


@pytest.mark.parametrize("stock,pending", [(75, 0), (20, 50), (5, 100)])
def test_sufficient_stock_and_pending_message_explains_14_day_target(
    app, replenishment_data, stock, pending
):
    with app.app_context():
        product = db.session.get(Product, replenishment_data["product_id"])
        product.stock = stock
        purchase = PurchaseOrder.query.one()
        if pending:
            purchase.items[0].quantity = pending
        else:
            purchase.status = "completed"
        db.session.commit()

        response = prepare_replenishment_purchase(product_name="机械键盘")

        assert response.type == "message"
        assert f"当前库存 {stock} 个" in response.content
        assert f"待入库 {pending} 个" in response.content
        assert "14 天" in response.content
        assert "不需要补货" in response.content
        assert response.preview is None
        assert PurchaseOrder.query.count() == 1


def test_fallback_price_uses_product_purchase_price_without_history(
    app, replenishment_data
):
    with app.app_context():
        product = Product(
            name="无采购历史键盘",
            sku="KB-FALLBACK",
            purchase_price=66,
            sale_price=90,
            stock=0,
        )
        customer = Customer.query.one()
        db.session.add(product)
        db.session.flush()
        sales_order = SalesOrder(
            order_no="SO-FALLBACK",
            customer_id=customer.id,
            status="completed",
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        sales_order.items.append(
            SalesOrderItem(product_id=product.id, quantity=35, unit_price=90)
        )
        db.session.add(sales_order)
        db.session.commit()

        response = prepare_replenishment_purchase(product_name="无采购历史键盘")

        assert response.type == "confirmation"
        assert response.preview["items"][0]["unit_price"] == "66.00"
        assert response.preview["price_source"] == "product_purchase_price"
