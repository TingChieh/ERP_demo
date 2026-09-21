from pathlib import Path

import pytest
from sqlalchemy import event

from app import create_app
from models import (
    AccountReceivable,
    Customer,
    InventoryTransaction,
    Product,
    SalesOrder,
    SalesOrderItem,
    db,
)


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'sales_shipment.db'}",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def shipment_data(app):
    with app.app_context():
        customer = Customer(name="大圣科技", phone="")
        keyboard = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=100
        )
        mouse = Product(
            name="鼠标", sku="MS001", purchase_price=40, sale_price=69, stock=10
        )
        db.session.add_all([customer, keyboard, mouse])
        db.session.commit()
        return {
            "customer_id": customer.id,
            "keyboard_id": keyboard.id,
            "mouse_id": mouse.id,
        }


def create_pending_order(app, shipment_data, lines, status="pending_shipment"):
    with app.app_context():
        order = SalesOrder(
            order_no=f"SO-TEST-{SalesOrder.query.count() + 1}",
            customer_id=shipment_data["customer_id"],
            status=status,
            total_amount=sum(
                quantity * unit_price for _, quantity, unit_price in lines
            ),
        )
        db.session.add(order)
        for product_id, quantity, unit_price in lines:
            db.session.add(
                SalesOrderItem(
                    sales_order=order,
                    product_id=product_id,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            )
        db.session.commit()
        return order.id


def test_pending_shipment_can_be_shipped(app, shipment_data):
    order_id = create_pending_order(
        app, shipment_data, [(shipment_data["keyboard_id"], 20, 120)]
    )

    response = app.test_client().post(f"/sales-orders/{order_id}/ship")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(SalesOrder, order_id).status == "completed"


def test_single_product_shipment_decreases_stock(app, shipment_data):
    order_id = create_pending_order(
        app, shipment_data, [(shipment_data["keyboard_id"], 20, 120)]
    )

    app.test_client().post(f"/sales-orders/{order_id}/ship")

    with app.app_context():
        assert db.session.get(Product, shipment_data["keyboard_id"]).stock == 80


def test_multi_product_shipment_decreases_each_stock_and_creates_two_transactions(
    app, shipment_data
):
    order_id = create_pending_order(
        app,
        shipment_data,
        [
            (shipment_data["keyboard_id"], 20, 120),
            (shipment_data["mouse_id"], 10, 69),
        ],
    )

    app.test_client().post(f"/sales-orders/{order_id}/ship")

    with app.app_context():
        transactions = InventoryTransaction.query.order_by(
            InventoryTransaction.product_id
        ).all()
        assert db.session.get(Product, shipment_data["keyboard_id"]).stock == 80
        assert db.session.get(Product, shipment_data["mouse_id"]).stock == 0
        assert len(transactions) == 2
        assert all(transaction.type == "outbound" for transaction in transactions)
        assert [transaction.quantity for transaction in transactions] == [20, 10]


def test_outbound_transaction_quantity_balance_and_order_number_are_correct(
    app, shipment_data
):
    order_id = create_pending_order(
        app, shipment_data, [(shipment_data["keyboard_id"], 20, 120)]
    )

    app.test_client().post(f"/sales-orders/{order_id}/ship")

    with app.app_context():
        order = db.session.get(SalesOrder, order_id)
        transaction = InventoryTransaction.query.one()
        assert transaction.quantity > 0
        assert transaction.quantity == 20
        assert transaction.balance_after == 80
        assert transaction.related_order_no == order.order_no


def test_shipment_creates_one_unpaid_receivable_from_order_total(
    app, shipment_data
):
    order_id = create_pending_order(
        app,
        shipment_data,
        [
            (shipment_data["keyboard_id"], 20, 120),
            (shipment_data["mouse_id"], 10, 69),
        ],
    )

    app.test_client().post(f"/sales-orders/{order_id}/ship")

    with app.app_context():
        order = db.session.get(SalesOrder, order_id)
        receivable = AccountReceivable.query.one()
        assert AccountReceivable.query.count() == 1
        assert receivable.sales_order_id == order_id
        assert receivable.customer_id == shipment_data["customer_id"]
        assert receivable.amount == order.total_amount == 3090
        assert receivable.status == "unpaid"


def test_completed_shipment_is_visible_on_order_detail(app, shipment_data):
    order_id = create_pending_order(
        app, shipment_data, [(shipment_data["keyboard_id"], 2, 120)]
    )
    app.test_client().post(f"/sales-orders/{order_id}/ship")

    response = app.test_client().get(f"/sales-orders/{order_id}")

    assert response.status_code == 200
    assert "已完成出库" in response.get_data(as_text=True)
    assert "应收账款" in response.get_data(as_text=True)
    assert "库存出库流水" in response.get_data(as_text=True)


def test_completed_order_cannot_be_shipped_again(app, shipment_data):
    order_id = create_pending_order(
        app, shipment_data, [(shipment_data["keyboard_id"], 20, 120)]
    )
    client = app.test_client()
    assert client.post(f"/sales-orders/{order_id}/ship").status_code == 302

    response = client.post(f"/sales-orders/{order_id}/ship")

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(Product, shipment_data["keyboard_id"]).stock == 80
        assert InventoryTransaction.query.count() == 1
        assert AccountReceivable.query.count() == 1


def test_draft_order_cannot_be_shipped(app, shipment_data):
    order_id = create_pending_order(
        app,
        shipment_data,
        [(shipment_data["keyboard_id"], 1, 120)],
        status="draft",
    )

    response = app.test_client().post(f"/sales-orders/{order_id}/ship")

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(SalesOrder, order_id).status == "draft"
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


def test_single_product_insufficient_stock_fails_without_any_change(
    app, shipment_data
):
    order_id = create_pending_order(
        app, shipment_data, [(shipment_data["keyboard_id"], 101, 120)]
    )

    response = app.test_client().post(f"/sales-orders/{order_id}/ship")

    assert response.status_code == 400
    assert "库存不足，无法出库" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Product, shipment_data["keyboard_id"]).stock == 100
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0
        assert db.session.get(SalesOrder, order_id).status == "pending_shipment"


def test_multi_product_insufficient_stock_fails_as_a_whole(app, shipment_data):
    order_id = create_pending_order(
        app,
        shipment_data,
        [
            (shipment_data["keyboard_id"], 20, 120),
            (shipment_data["mouse_id"], 11, 69),
        ],
    )

    response = app.test_client().post(f"/sales-orders/{order_id}/ship")

    assert response.status_code == 400
    assert "库存不足，无法出库" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Product, shipment_data["keyboard_id"]).stock == 100
        assert db.session.get(Product, shipment_data["mouse_id"]).stock == 10
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0
        assert db.session.get(SalesOrder, order_id).status == "pending_shipment"


def test_ship_rolls_back_all_changes_when_second_transaction_fails(
    app, shipment_data
):
    order_id = create_pending_order(
        app,
        shipment_data,
        [
            (shipment_data["keyboard_id"], 20, 120),
            (shipment_data["mouse_id"], 10, 69),
        ],
    )

    def fail_for_mouse(mapper, connection, target):
        if target.product_id == shipment_data["mouse_id"]:
            raise RuntimeError("simulated shipment failure")

    event.listen(InventoryTransaction, "before_insert", fail_for_mouse)
    try:
        response = app.test_client().post(f"/sales-orders/{order_id}/ship")
    finally:
        event.remove(InventoryTransaction, "before_insert", fail_for_mouse)

    assert response.status_code == 500
    with app.app_context():
        assert db.session.get(Product, shipment_data["keyboard_id"]).stock == 100
        assert db.session.get(Product, shipment_data["mouse_id"]).stock == 10
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0
        assert db.session.get(SalesOrder, order_id).status == "pending_shipment"
