from datetime import datetime
from pathlib import Path
import re

import pytest

from app import create_app
from models import (
    AccountPayable,
    AccountReceivable,
    Customer,
    InventoryTransaction,
    Product,
    PurchaseOrder,
    SalesOrder,
    Supplier,
    db,
)


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'settlements.db'}",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def settlement_data(app):
    with app.app_context():
        customer = Customer(name="大圣科技", phone="")
        supplier = Supplier(name="南京键盘供应商", phone="")
        product = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=100
        )
        sales_order = SalesOrder(
            order_no="SO-SETTLEMENT-001",
            customer=customer,
            status="completed",
            total_amount=2400,
        )
        purchase_order = PurchaseOrder(
            order_no="PO-SETTLEMENT-001",
            supplier=supplier,
            status="completed",
            total_amount=8000,
        )
        db.session.add_all([customer, supplier, product, sales_order, purchase_order])
        db.session.flush()

        unpaid_receivable = AccountReceivable(
            sales_order_id=sales_order.id,
            customer_id=customer.id,
            amount=2400,
            status="unpaid",
        )
        paid_sales_order = SalesOrder(
            order_no="SO-SETTLEMENT-002",
            customer=customer,
            status="completed",
            total_amount=100,
        )
        db.session.add(paid_sales_order)
        db.session.flush()
        paid_receivable = AccountReceivable(
            sales_order_id=paid_sales_order.id,
            customer_id=customer.id,
            amount=100,
            status="paid",
            paid_at=datetime(2026, 1, 1, 12, 0, 0),
        )

        unpaid_payable = AccountPayable(
            purchase_order_id=purchase_order.id,
            supplier_id=supplier.id,
            amount=8000,
            status="unpaid",
        )
        paid_purchase_order = PurchaseOrder(
            order_no="PO-SETTLEMENT-002",
            supplier=supplier,
            status="completed",
            total_amount=100,
        )
        db.session.add(paid_purchase_order)
        db.session.flush()
        paid_payable = AccountPayable(
            purchase_order_id=paid_purchase_order.id,
            supplier_id=supplier.id,
            amount=100,
            status="paid",
            paid_at=datetime(2026, 1, 1, 12, 0, 0),
        )

        db.session.add_all(
            [unpaid_receivable, paid_receivable, unpaid_payable, paid_payable]
        )
        db.session.commit()
        return {
            "customer_id": customer.id,
            "supplier_id": supplier.id,
            "product_id": product.id,
            "sales_order_id": sales_order.id,
            "purchase_order_id": purchase_order.id,
            "receivable_id": unpaid_receivable.id,
            "payable_id": unpaid_payable.id,
        }


def test_receivables_list_returns_200(app, settlement_data):
    response = app.test_client().get("/receivables")

    assert response.status_code == 200
    assert "应收账款" in response.get_data(as_text=True)


def test_payables_list_returns_200(app, settlement_data):
    response = app.test_client().get("/payables")

    assert response.status_code == 200
    assert "应付账款" in response.get_data(as_text=True)


def test_unpaid_receivable_can_be_received_in_full(app, settlement_data):
    response = app.test_client().post(
        f"/receivables/{settlement_data['receivable_id']}/receive-payment"
    )

    assert response.status_code == 302
    with app.app_context():
        receivable = db.session.get(AccountReceivable, settlement_data["receivable_id"])
        assert receivable.status == "paid"
        assert receivable.paid_at is not None


def test_receivable_payment_does_not_change_operational_records(app, settlement_data):
    with app.app_context():
        before_stock = db.session.get(Product, settlement_data["product_id"]).stock
        before_order = db.session.get(SalesOrder, settlement_data["sales_order_id"])
        before_status = before_order.status
        before_total = before_order.total_amount

    app.test_client().post(
        f"/receivables/{settlement_data['receivable_id']}/receive-payment"
    )

    with app.app_context():
        assert db.session.get(Product, settlement_data["product_id"]).stock == before_stock
        assert InventoryTransaction.query.count() == 0
        order = db.session.get(SalesOrder, settlement_data["sales_order_id"])
        assert order.status == before_status
        assert order.total_amount == before_total


def test_paid_receivable_cannot_be_received_again(app, settlement_data):
    client = app.test_client()
    receivable_id = settlement_data["receivable_id"]
    assert client.post(f"/receivables/{receivable_id}/receive-payment").status_code == 302

    with app.app_context():
        first_paid_at = db.session.get(AccountReceivable, receivable_id).paid_at

    response = client.post(f"/receivables/{receivable_id}/receive-payment")

    assert response.status_code == 400
    assert "该应收账款已收款" in response.get_data(as_text=True)
    with app.app_context():
        receivable = db.session.get(AccountReceivable, receivable_id)
        assert receivable.status == "paid"
        assert receivable.paid_at == first_paid_at
        assert AccountReceivable.query.count() == 2


def test_unpaid_payable_can_be_paid_in_full(app, settlement_data):
    response = app.test_client().post(
        f"/payables/{settlement_data['payable_id']}/pay"
    )

    assert response.status_code == 302
    with app.app_context():
        payable = db.session.get(AccountPayable, settlement_data["payable_id"])
        assert payable.status == "paid"
        assert payable.paid_at is not None


def test_payable_payment_does_not_change_operational_records(app, settlement_data):
    with app.app_context():
        before_stock = db.session.get(Product, settlement_data["product_id"]).stock
        before_order = db.session.get(PurchaseOrder, settlement_data["purchase_order_id"])
        before_status = before_order.status
        before_total = before_order.total_amount

    app.test_client().post(f"/payables/{settlement_data['payable_id']}/pay")

    with app.app_context():
        assert db.session.get(Product, settlement_data["product_id"]).stock == before_stock
        assert InventoryTransaction.query.count() == 0
        order = db.session.get(PurchaseOrder, settlement_data["purchase_order_id"])
        assert order.status == before_status
        assert order.total_amount == before_total


def test_paid_payable_cannot_be_paid_again(app, settlement_data):
    client = app.test_client()
    payable_id = settlement_data["payable_id"]
    assert client.post(f"/payables/{payable_id}/pay").status_code == 302

    with app.app_context():
        first_paid_at = db.session.get(AccountPayable, payable_id).paid_at

    response = client.post(f"/payables/{payable_id}/pay")

    assert response.status_code == 400
    assert "该应付账款已付款" in response.get_data(as_text=True)
    with app.app_context():
        payable = db.session.get(AccountPayable, payable_id)
        assert payable.status == "paid"
        assert payable.paid_at == first_paid_at
        assert AccountPayable.query.count() == 2


def test_dashboard_unpaid_receivable_total_is_database_backed(app, settlement_data):
    response = app.test_client().get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(
        r"未收应收账款</div>\s*<div[^>]*>¥ 2400\.00</div>", html
    )


def test_dashboard_unpaid_payable_total_is_database_backed(app, settlement_data):
    response = app.test_client().get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(
        r"未付应付账款</div>\s*<div[^>]*>¥ 8000\.00</div>", html
    )
