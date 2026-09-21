from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

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
from services.replenishment import (
    analyze_replenishment,
    calculate_days_of_inventory,
    calculate_recommended_purchase_qty,
    get_last_purchase_price,
    get_low_stock_analyses,
    get_pending_purchase_quantity,
    get_sales_quantity,
)


AS_OF = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'replenishment.db'}",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def data(app):
    with app.app_context():
        supplier = Supplier(name="供应商", phone="")
        customer = Customer(name="客户", phone="")
        product = Product(
            name="测试商品", sku="TEST-001", purchase_price=50, sale_price=80, stock=20
        )
        db.session.add_all([supplier, customer, product])
        db.session.flush()

        def add_order(order_no, status, age_days, quantity):
            order = SalesOrder(
                order_no=order_no,
                customer_id=customer.id,
                status=status,
                created_at=AS_OF - timedelta(days=age_days),
            )
            order.items.append(
                SalesOrderItem(product_id=product.id, quantity=quantity, unit_price=80)
            )
            db.session.add(order)

        add_order("SO-COMPLETED-7D", "completed", 3, 35)
        add_order("SO-COMPLETED-30D", "completed", 20, 12)
        add_order("SO-COMPLETED-OLD", "completed", 31, 99)
        add_order("SO-DRAFT", "draft", 2, 100)
        add_order("SO-PENDING", "pending_shipment", 2, 100)
        db.session.commit()
        return {
            "product_id": product.id,
            "supplier_id": supplier.id,
            "customer_id": customer.id,
        }


@pytest.fixture()
def product_without_history(app):
    with app.app_context():
        product = Product(
            name="无历史商品",
            sku="NO-HISTORY",
            purchase_price=25,
            sale_price=40,
            stock=0,
        )
        db.session.add(product)
        db.session.commit()
        db.session.refresh(product)
        db.session.expunge(product)
        return product


def test_get_sales_quantity_counts_completed_orders_in_the_requested_window(app, data):
    with app.app_context():
        assert get_sales_quantity(data["product_id"], 7, as_of=AS_OF) == 35
        assert get_sales_quantity(data["product_id"], 30, as_of=AS_OF) == 47


def test_get_sales_quantity_excludes_draft_and_pending_shipment_orders(app, data):
    with app.app_context():
        assert get_sales_quantity(data["product_id"], 30, as_of=AS_OF) == 47


def test_pending_purchase_quantity_only_counts_pending_receipt(app, data):
    with app.app_context():
        for order_no, status, quantity in (
            ("PO-PENDING", "pending_receipt", 10),
            ("PO-DRAFT", "draft", 20),
            ("PO-COMPLETED", "completed", 30),
        ):
            order = PurchaseOrder(
                order_no=order_no,
                supplier_id=data["supplier_id"],
                status=status,
                created_at=AS_OF - timedelta(days=5),
            )
            order.items.append(
                PurchaseOrderItem(
                    product_id=data["product_id"], quantity=quantity, unit_price=78
                )
            )
            db.session.add(order)
        db.session.commit()

        assert get_pending_purchase_quantity(data["product_id"]) == 10


def test_last_purchase_price_uses_the_most_recent_purchase_item(app, data):
    with app.app_context():
        old_order = PurchaseOrder(
            order_no="PO-OLD",
            supplier_id=data["supplier_id"],
            status="completed",
            created_at=AS_OF - timedelta(days=10),
        )
        old_order.items.append(
            PurchaseOrderItem(product_id=data["product_id"], quantity=2, unit_price=70)
        )
        new_order = PurchaseOrder(
            order_no="PO-NEW",
            supplier_id=data["supplier_id"],
            status="pending_receipt",
            created_at=AS_OF - timedelta(days=2),
        )
        new_order.items.append(
            PurchaseOrderItem(product_id=data["product_id"], quantity=2, unit_price=78)
        )
        db.session.add_all([old_order, new_order])
        db.session.commit()

        assert get_last_purchase_price(data["product_id"]) == Decimal("78.00")


def test_last_purchase_price_returns_none_without_history(app, product_without_history):
    with app.app_context():
        assert get_last_purchase_price(product_without_history.id) is None


def test_analysis_preserves_latest_zero_purchase_price(app, data):
    with app.app_context():
        order = PurchaseOrder(
            order_no="PO-ZERO-PRICE",
            supplier_id=data["supplier_id"],
            status="completed",
            created_at=AS_OF - timedelta(days=1),
        )
        order.items.append(
            PurchaseOrderItem(
                product_id=data["product_id"], quantity=1, unit_price=Decimal("0.00")
            )
        )
        db.session.add(order)
        db.session.commit()

        analysis = analyze_replenishment(data["product_id"], as_of=AS_OF)

    assert analysis["last_purchase_price"] == "0.00"
    assert analysis["purchase_price"] == "0.00"


def test_days_of_inventory_uses_recent_average(app):
    assert calculate_days_of_inventory(20, Decimal("5")) == Decimal("4.00")


def test_days_of_inventory_is_none_without_recent_sales(app):
    assert calculate_days_of_inventory(0, Decimal("0")) is None


def test_recommended_purchase_qty_uses_stock_and_pending_receipts(app):
    assert calculate_recommended_purchase_qty(20, 10, Decimal("5")) == 40


def test_recommended_purchase_qty_is_zero_when_pending_receipt_is_enough(app):
    assert calculate_recommended_purchase_qty(5, 100, Decimal("5")) == 0


def test_zero_stock_without_sales_is_not_low_stock(app, product_without_history):
    with app.app_context():
        analysis = analyze_replenishment(product_without_history.id, as_of=AS_OF)

    assert analysis["days_of_inventory"] is None
    assert analysis["recommended_purchase_qty"] == 0
    assert analysis["low_stock"] is False


@pytest.fixture()
def analysis_data(app, data):
    with app.app_context():
        product = Product(
            name="分析商品", sku="ANALYSIS-001", purchase_price=60, sale_price=90, stock=20
        )
        db.session.add(product)
        db.session.flush()
        order = SalesOrder(
            order_no="SO-ANALYSIS",
            customer_id=data["customer_id"],
            status="completed",
            created_at=AS_OF - timedelta(days=3),
        )
        order.items.append(
            SalesOrderItem(product_id=product.id, quantity=35, unit_price=90)
        )
        purchase = PurchaseOrder(
            order_no="PO-ANALYSIS",
            supplier_id=data["supplier_id"],
            status="pending_receipt",
            created_at=AS_OF - timedelta(days=2),
        )
        purchase.items.append(
            PurchaseOrderItem(product_id=product.id, quantity=10, unit_price=60)
        )
        db.session.add_all([order, purchase])
        db.session.commit()
        return {"product_id": product.id}


def test_analyze_replenishment_returns_dashboard_metrics(app, analysis_data):
    with app.app_context():
        analysis = analyze_replenishment(analysis_data["product_id"], as_of=AS_OF)

    assert analysis == {
        "product_id": analysis_data["product_id"],
        "product_name": "分析商品",
        "sku": "ANALYSIS-001",
        "current_stock": 20,
        "sales_7d": 35,
        "sales_30d": 35,
        "avg_daily_sales_7d": 5,
        "avg_daily_sales_30d": 1.17,
        "pending_purchase_qty": 10,
        "days_of_inventory": 4,
        "recommended_purchase_qty": 40,
        "default_purchase_price": "60.00",
        "last_purchase_price": "60.00",
        "purchase_price": "60.00",
        "low_stock": True,
    }


def test_get_low_stock_analyses_limits_and_excludes_no_sales(
    app, product_without_history, analysis_data
):
    with app.app_context():
        analyses = get_low_stock_analyses(limit=5, as_of=AS_OF)

    assert len(analyses) <= 5
    assert analysis_data["product_id"] in {item["product_id"] for item in analyses}
    assert product_without_history.id not in {item["product_id"] for item in analyses}
