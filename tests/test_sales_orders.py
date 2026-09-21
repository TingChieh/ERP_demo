from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

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
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'sales_orders.db'}",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def master_data(app):
    with app.app_context():
        customer = Customer(name="大圣科技", phone="")
        keyboard = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=5
        )
        mouse = Product(
            name="鼠标", sku="MS001", purchase_price=40, sale_price=69, stock=20
        )
        db.session.add_all([customer, keyboard, mouse])
        db.session.commit()
        return {
            "customer_id": customer.id,
            "keyboard_id": keyboard.id,
            "mouse_id": mouse.id,
        }


def sales_form(customer_id, lines, total_amount=None):
    data = MultiDict([("customer_id", str(customer_id))])
    for product_id, quantity, unit_price in lines:
        data.add("product_ids", str(product_id))
        data[f"quantity_{product_id}"] = str(quantity)
        data[f"unit_price_{product_id}"] = str(unit_price)
    if total_amount is not None:
        data["total_amount"] = str(total_amount)
    return data


def test_sales_order_list_returns_200(app):
    response = app.test_client().get("/sales-orders")

    assert response.status_code == 200
    assert "销售订单" in response.get_data(as_text=True)


def test_can_create_single_line_sales_order_without_side_effects(app, master_data):
    response = app.test_client().post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(master_data["keyboard_id"], 20, "120")],
        ),
    )

    assert response.status_code == 302
    with app.app_context():
        order = SalesOrder.query.one()
        item = SalesOrderItem.query.one()
        assert order.status == "draft"
        assert order.order_no.startswith("SO")
        assert item.quantity == 20
        assert item.unit_price == 120
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 5
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


def test_can_create_multiple_line_sales_order_and_calculates_total(app, master_data):
    response = app.test_client().post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [
                (master_data["keyboard_id"], 20, "120"),
                (master_data["mouse_id"], 3, "65.50"),
            ],
        ),
    )

    assert response.status_code == 302
    with app.app_context():
        order = SalesOrder.query.one()
        assert order.total_amount == 2596.50
        assert SalesOrderItem.query.filter_by(sales_order_id=order.id).count() == 2


def test_sales_order_detail_returns_200(app, master_data):
    client = app.test_client()
    client.post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(master_data["keyboard_id"], 1, "120")],
        ),
    )
    with app.app_context():
        order = SalesOrder.query.one()

    response = client.get(f"/sales-orders/{order.id}")

    assert response.status_code == 200
    assert order.order_no.encode() in response.data


def test_client_total_amount_is_ignored(app, master_data):
    app.test_client().post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(master_data["keyboard_id"], 2, "120")],
            total_amount="1",
        ),
    )

    with app.app_context():
        assert SalesOrder.query.one().total_amount == 240


def test_non_positive_quantity_fails_and_creates_no_order(app, master_data):
    response = app.test_client().post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(master_data["keyboard_id"], 0, "120")],
        ),
    )

    assert response.status_code == 200
    with app.app_context():
        assert SalesOrder.query.count() == 0


def test_unknown_customer_fails_and_creates_no_order(app, master_data):
    response = app.test_client().post(
        "/sales-orders/new",
        data=sales_form(9999, [(master_data["keyboard_id"], 1, "120")]),
    )

    assert response.status_code == 200
    with app.app_context():
        assert SalesOrder.query.count() == 0


def test_unknown_product_fails_and_creates_no_order(app, master_data):
    response = app.test_client().post(
        "/sales-orders/new",
        data=sales_form(master_data["customer_id"], [(9999, 1, "120")]),
    )

    assert response.status_code == 200
    with app.app_context():
        assert SalesOrder.query.count() == 0


def test_duplicate_product_line_fails_and_creates_no_order(app, master_data):
    product_id = master_data["keyboard_id"]
    response = app.test_client().post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(product_id, 1, "120"), (product_id, 2, "119")],
        ),
    )

    assert response.status_code == 200
    with app.app_context():
        assert SalesOrder.query.count() == 0


def test_insufficient_stock_still_allows_sales_order_creation(app, master_data):
    response = app.test_client().post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(master_data["keyboard_id"], 10, "120")],
        ),
    )

    assert response.status_code == 302
    with app.app_context():
        assert SalesOrder.query.one().items[0].quantity == 10
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 5


def test_draft_can_be_submitted_to_pending_shipment(app, master_data):
    client = app.test_client()
    client.post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(master_data["keyboard_id"], 1, "120")],
        ),
    )
    with app.app_context():
        order_id = SalesOrder.query.one().id

    response = client.post(f"/sales-orders/{order_id}/submit")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(SalesOrder, order_id).status == "pending_shipment"
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


def test_pending_shipment_cannot_be_submitted_again(app, master_data):
    client = app.test_client()
    client.post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(master_data["keyboard_id"], 1, "120")],
        ),
    )
    with app.app_context():
        order_id = SalesOrder.query.one().id

    assert client.post(f"/sales-orders/{order_id}/submit").status_code == 302
    response = client.post(f"/sales-orders/{order_id}/submit")

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(SalesOrder, order_id).status == "pending_shipment"
