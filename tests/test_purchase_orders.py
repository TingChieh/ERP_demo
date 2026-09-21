from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

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
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'purchase_orders.db'}",
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
        supplier = Supplier(name="南京键盘供应商", phone="")
        keyboard = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=7
        )
        mouse = Product(
            name="鼠标", sku="MS001", purchase_price=40, sale_price=69, stock=3
        )
        db.session.add_all([supplier, keyboard, mouse])
        db.session.commit()
        return {
            "supplier_id": supplier.id,
            "keyboard_id": keyboard.id,
            "mouse_id": mouse.id,
        }


def purchase_form(supplier_id, lines, total_amount=None):
    data = MultiDict([("supplier_id", str(supplier_id))])
    for product_id, quantity, unit_price in lines:
        data.add("product_ids", str(product_id))
        data[f"quantity_{product_id}"] = str(quantity)
        data[f"unit_price_{product_id}"] = str(unit_price)
    if total_amount is not None:
        data["total_amount"] = str(total_amount)
    return data


def test_purchase_order_list_returns_200(app):
    response = app.test_client().get("/purchase-orders")

    assert response.status_code == 200
    assert "采购订单" in response.get_data(as_text=True)


def test_can_create_single_line_purchase_order_without_side_effects(app, master_data):
    data = purchase_form(
        master_data["supplier_id"],
        [(master_data["keyboard_id"], 100, "80")],
    )

    response = app.test_client().post("/purchase-orders/new", data=data)

    assert response.status_code == 302
    with app.app_context():
        order = PurchaseOrder.query.one()
        item = PurchaseOrderItem.query.one()
        assert order.status == "draft"
        assert order.order_no.startswith("PO")
        assert item.quantity == 100
        assert item.unit_price == 80
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 7
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0


def test_can_create_multiple_line_purchase_order_and_calculates_total(app, master_data):
    data = purchase_form(
        master_data["supplier_id"],
        [
            (master_data["keyboard_id"], 100, "80"),
            (master_data["mouse_id"], 5, "35.50"),
        ],
    )

    response = app.test_client().post("/purchase-orders/new", data=data)

    assert response.status_code == 302
    with app.app_context():
        order = PurchaseOrder.query.one()
        assert order.total_amount == 8177.50
        assert PurchaseOrderItem.query.filter_by(purchase_order_id=order.id).count() == 2


def test_purchase_order_detail_returns_200(app, master_data):
    client = app.test_client()
    client.post(
        "/purchase-orders/new",
        data=purchase_form(
            master_data["supplier_id"],
            [(master_data["keyboard_id"], 1, "80")],
        ),
    )
    with app.app_context():
        order = PurchaseOrder.query.one()

    response = client.get(f"/purchase-orders/{order.id}")

    assert response.status_code == 200
    assert order.order_no.encode() in response.data


def test_generated_purchase_order_numbers_are_unique(app, master_data):
    client = app.test_client()
    data = purchase_form(
        master_data["supplier_id"],
        [(master_data["keyboard_id"], 1, "80")],
    )

    assert client.post("/purchase-orders/new", data=data).status_code == 302
    assert client.post("/purchase-orders/new", data=data).status_code == 302

    with app.app_context():
        order_numbers = [order.order_no for order in PurchaseOrder.query.all()]
        assert len(order_numbers) == 2
        assert len(set(order_numbers)) == 2


def test_client_total_amount_is_ignored(app, master_data):
    data = purchase_form(
        master_data["supplier_id"],
        [(master_data["keyboard_id"], 2, "80")],
        total_amount="1",
    )

    app.test_client().post("/purchase-orders/new", data=data)

    with app.app_context():
        assert PurchaseOrder.query.one().total_amount == 160


def test_non_positive_quantity_fails_and_creates_no_order(app, master_data):
    response = app.test_client().post(
        "/purchase-orders/new",
        data=purchase_form(
            master_data["supplier_id"],
            [(master_data["keyboard_id"], 0, "80")],
        ),
    )

    assert response.status_code == 200
    with app.app_context():
        assert PurchaseOrder.query.count() == 0


def test_unknown_supplier_fails_and_creates_no_order(app, master_data):
    response = app.test_client().post(
        "/purchase-orders/new",
        data=purchase_form(9999, [(master_data["keyboard_id"], 1, "80")]),
    )

    assert response.status_code == 200
    with app.app_context():
        assert PurchaseOrder.query.count() == 0


def test_unknown_product_fails_and_creates_no_order(app, master_data):
    response = app.test_client().post(
        "/purchase-orders/new",
        data=purchase_form(master_data["supplier_id"], [(9999, 1, "80")]),
    )

    assert response.status_code == 200
    with app.app_context():
        assert PurchaseOrder.query.count() == 0


def test_duplicate_product_line_fails_and_creates_no_order(app, master_data):
    product_id = master_data["keyboard_id"]
    response = app.test_client().post(
        "/purchase-orders/new",
        data=purchase_form(
            master_data["supplier_id"],
            [(product_id, 1, "80"), (product_id, 2, "79")],
        ),
    )

    assert response.status_code == 200
    with app.app_context():
        assert PurchaseOrder.query.count() == 0


def test_draft_can_be_submitted_to_pending_receipt(app, master_data):
    client = app.test_client()
    client.post(
        "/purchase-orders/new",
        data=purchase_form(
            master_data["supplier_id"],
            [(master_data["keyboard_id"], 1, "80")],
        ),
    )
    with app.app_context():
        order_id = PurchaseOrder.query.one().id

    response = client.post(f"/purchase-orders/{order_id}/submit")

    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(PurchaseOrder, order_id).status == "pending_receipt"
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0


def test_pending_receipt_cannot_be_submitted_again(app, master_data):
    client = app.test_client()
    client.post(
        "/purchase-orders/new",
        data=purchase_form(
            master_data["supplier_id"],
            [(master_data["keyboard_id"], 1, "80")],
        ),
    )
    with app.app_context():
        order_id = PurchaseOrder.query.one().id

    assert client.post(f"/purchase-orders/{order_id}/submit").status_code == 302
    response = client.post(f"/purchase-orders/{order_id}/submit")

    assert response.status_code == 400
    with app.app_context():
        assert db.session.get(PurchaseOrder, order_id).status == "pending_receipt"
