from pathlib import Path

import pytest
from sqlalchemy import event

from app import create_app
from models import (
    AccountPayable,
    InventoryTransaction,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    db,
)


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'purchase_receipt.db'}",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def receipt_data(app):
    with app.app_context():
        supplier = Supplier(name="南京键盘供应商", phone="")
        keyboard = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=0
        )
        mouse = Product(
            name="鼠标", sku="MS001", purchase_price=40, sale_price=69, stock=10
        )
        db.session.add_all([supplier, keyboard, mouse])
        db.session.commit()
        return {
            "supplier_id": supplier.id,
            "keyboard_id": keyboard.id,
            "mouse_id": mouse.id,
        }


def create_pending_order(app, receipt_data, lines):
    with app.app_context():
        order = PurchaseOrder(
            order_no=f"PO-TEST-{PurchaseOrder.query.count() + 1}",
            supplier_id=receipt_data["supplier_id"],
            status="pending_receipt",
            total_amount=sum(
                quantity * unit_price for _, quantity, unit_price in lines
            ),
        )
        db.session.add(order)
        for product_id, quantity, unit_price in lines:
            db.session.add(
                PurchaseOrderItem(
                    purchase_order=order,
                    product_id=product_id,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            )
        db.session.commit()
        return order.id


def test_pending_receipt_can_be_received(app, receipt_data):
    order_id = create_pending_order(
        app, receipt_data, [(receipt_data["keyboard_id"], 100, 80)]
    )

    response = app.test_client().post(f"/purchase-orders/{order_id}/receive")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(PurchaseOrder, order_id).status == "completed"


def test_receipt_increases_product_stock(app, receipt_data):
    order_id = create_pending_order(
        app, receipt_data, [(receipt_data["keyboard_id"], 100, 80)]
    )

    app.test_client().post(f"/purchase-orders/{order_id}/receive")

    with app.app_context():
        assert db.session.get(Product, receipt_data["keyboard_id"]).stock == 100


def test_single_product_receipt_creates_one_inbound_transaction(app, receipt_data):
    order_id = create_pending_order(
        app, receipt_data, [(receipt_data["keyboard_id"], 100, 80)]
    )

    app.test_client().post(f"/purchase-orders/{order_id}/receive")

    with app.app_context():
        transaction = InventoryTransaction.query.one()
        order = db.session.get(PurchaseOrder, order_id)
        assert transaction.type == "inbound"
        assert transaction.quantity == 100
        assert transaction.related_order_no == order.order_no


def test_multi_product_receipt_creates_matching_transactions(app, receipt_data):
    order_id = create_pending_order(
        app,
        receipt_data,
        [
            (receipt_data["keyboard_id"], 100, 80),
            (receipt_data["mouse_id"], 50, 40),
        ],
    )

    app.test_client().post(f"/purchase-orders/{order_id}/receive")

    with app.app_context():
        transactions = InventoryTransaction.query.order_by(
            InventoryTransaction.product_id
        ).all()
        assert len(transactions) == 2
        assert [transaction.quantity for transaction in transactions] == [100, 50]
        assert all(transaction.type == "inbound" for transaction in transactions)
        assert db.session.get(Product, receipt_data["keyboard_id"]).stock == 100
        assert db.session.get(Product, receipt_data["mouse_id"]).stock == 60


def test_balance_after_records_post_receipt_stock(app, receipt_data):
    order_id = create_pending_order(
        app, receipt_data, [(receipt_data["mouse_id"], 50, 40)]
    )

    app.test_client().post(f"/purchase-orders/{order_id}/receive")

    with app.app_context():
        transaction = InventoryTransaction.query.one()
        assert transaction.balance_after == 60


def test_receipt_creates_one_unpaid_payable_from_order_total(app, receipt_data):
    order_id = create_pending_order(
        app,
        receipt_data,
        [
            (receipt_data["keyboard_id"], 100, 80),
            (receipt_data["mouse_id"], 50, 40),
        ],
    )

    app.test_client().post(f"/purchase-orders/{order_id}/receive")

    with app.app_context():
        order = db.session.get(PurchaseOrder, order_id)
        payable = AccountPayable.query.one()
        assert AccountPayable.query.count() == 1
        assert payable.purchase_order_id == order_id
        assert payable.supplier_id == receipt_data["supplier_id"]
        assert payable.amount == order.total_amount == 10000
        assert payable.status == "unpaid"


def test_completed_receipt_is_visible_on_order_detail(app, receipt_data):
    order_id = create_pending_order(
        app, receipt_data, [(receipt_data["keyboard_id"], 2, 80)]
    )
    app.test_client().post(f"/purchase-orders/{order_id}/receive")

    response = app.test_client().get(f"/purchase-orders/{order_id}")

    assert response.status_code == 200
    assert "已完成入库" in response.get_data(as_text=True)
    assert "应付账款" in response.get_data(as_text=True)
    assert "库存入库流水" in response.get_data(as_text=True)


def test_completed_order_cannot_be_received_again(app, receipt_data):
    order_id = create_pending_order(
        app, receipt_data, [(receipt_data["keyboard_id"], 100, 80)]
    )
    client = app.test_client()
    assert client.post(f"/purchase-orders/{order_id}/receive").status_code == 302

    response = client.post(f"/purchase-orders/{order_id}/receive")

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(Product, receipt_data["keyboard_id"]).stock == 100
        assert InventoryTransaction.query.count() == 1
        assert AccountPayable.query.count() == 1


def test_draft_order_cannot_be_received(app, receipt_data):
    with app.app_context():
        order = PurchaseOrder(
            order_no="PO-TEST-DRAFT",
            supplier_id=receipt_data["supplier_id"],
            status="draft",
            total_amount=80,
        )
        db.session.add(order)
        db.session.add(
            PurchaseOrderItem(
                purchase_order=order,
                product_id=receipt_data["keyboard_id"],
                quantity=1,
                unit_price=80,
            )
        )
        db.session.commit()
        order_id = order.id

    response = app.test_client().post(f"/purchase-orders/{order_id}/receive")

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(PurchaseOrder, order_id).status == "draft"
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0


def test_receive_rolls_back_all_changes_when_second_transaction_fails(
    app, receipt_data
):
    order_id = create_pending_order(
        app,
        receipt_data,
        [
            (receipt_data["keyboard_id"], 100, 80),
            (receipt_data["mouse_id"], 50, 40),
        ],
    )

    def fail_for_mouse(mapper, connection, target):
        if target.product_id == receipt_data["mouse_id"]:
            raise RuntimeError("simulated inventory failure")

    event.listen(InventoryTransaction, "before_insert", fail_for_mouse)
    try:
        response = app.test_client().post(f"/purchase-orders/{order_id}/receive")
    finally:
        event.remove(InventoryTransaction, "before_insert", fail_for_mouse)

    assert response.status_code == 500
    with app.app_context():
        assert db.session.get(Product, receipt_data["keyboard_id"]).stock == 0
        assert db.session.get(Product, receipt_data["mouse_id"]).stock == 10
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0
        assert db.session.get(PurchaseOrder, order_id).status == "pending_receipt"
