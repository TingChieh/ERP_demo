from pathlib import Path

import pytest

from app import create_app
from init_db import initialize_database
from models import (
    AccountPayable,
    AccountReceivable,
    Customer,
    InventoryTransaction,
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
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_database_schema_contains_confirmed_tables_and_balance_after(app):
    expected_tables = {
        "product",
        "supplier",
        "customer",
        "purchase_order",
        "purchase_order_item",
        "sales_order",
        "sales_order_item",
        "inventory_transaction",
        "account_receivable",
        "account_payable",
    }

    with app.app_context():
        assert expected_tables.issubset(set(db.metadata.tables))
        assert "balance_after" in InventoryTransaction.__table__.columns


def test_demo_data_initialization_is_idempotent(app):
    initialize_database(app)
    initialize_database(app)

    with app.app_context():
        assert Product.query.count() == 2
        assert Supplier.query.filter_by(name="南京键盘供应商").count() == 1
        assert Customer.query.filter_by(name="大圣科技").count() == 1
        assert Product.query.filter_by(sku="KB001").one().stock == 0


def test_dashboard_is_available_without_business_workflows(app):
    response = app.test_client().get("/")

    assert response.status_code == 200
    assert "Dashboard" in response.get_data(as_text=True)


def test_confirmed_model_imports_are_available():
    assert all(
        model is not None
        for model in (
            Product,
            Supplier,
            Customer,
            PurchaseOrder,
            PurchaseOrderItem,
            SalesOrder,
            SalesOrderItem,
            InventoryTransaction,
            AccountReceivable,
            AccountPayable,
        )
    )
