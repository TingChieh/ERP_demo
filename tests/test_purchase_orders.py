from pathlib import Path
from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import MultiDict

from app import create_app
from models import (
    AccountPayable,
    DatabaseOperationLog,
    InventoryTransaction,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    db,
)
from services.orders import (
    create_purchase_order_draft,
    delete_purchase_order_draft,
    update_purchase_order_draft,
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
        alternate_supplier = Supplier(name="上海鼠标供应商", phone="")
        keyboard = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=7
        )
        mouse = Product(
            name="鼠标", sku="MS001", purchase_price=40, sale_price=69, stock=3
        )
        db.session.add_all([supplier, alternate_supplier, keyboard, mouse])
        db.session.commit()
        return {
            "supplier_id": supplier.id,
            "alternate_supplier_id": alternate_supplier.id,
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


def test_shared_purchase_service_creates_validated_draft(app, master_data):
    with app.app_context():
        order = create_purchase_order_draft(
            master_data["supplier_id"],
            [
                {
                    "product_id": master_data["keyboard_id"],
                    "quantity": 2,
                    "unit_price": Decimal("78.00"),
                }
            ],
        )

        assert order.status == "draft"
        assert order.total_amount == Decimal("156.00")
        assert order.items[0].product_id == master_data["keyboard_id"]
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0


def test_shared_purchase_service_rejects_duplicate_products_without_order(
    app, master_data
):
    with app.app_context():
        with pytest.raises(ValueError, match="不能重复"):
            create_purchase_order_draft(
                master_data["supplier_id"],
                [
                    {
                        "product_id": master_data["keyboard_id"],
                        "quantity": 1,
                        "unit_price": Decimal("78.00"),
                    },
                    {
                        "product_id": master_data["keyboard_id"],
                        "quantity": 2,
                        "unit_price": Decimal("77.00"),
                    },
                ],
            )

        assert PurchaseOrder.query.count() == 0


def test_update_purchase_order_draft_replaces_lines_and_total(app, master_data):
    with app.app_context():
        order = create_purchase_order_draft(
            master_data["supplier_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "80"}],
        )
        original_order_no = order.order_no
        original_created_at = order.created_at
        original_supplier_id = order.supplier_id

        updated = update_purchase_order_draft(
            order,
            master_data["alternate_supplier_id"],
            [{"product_id": master_data["mouse_id"], "quantity": 3, "unit_price": "35.50"}],
        )

        assert updated.status == "draft"
        assert updated.order_no == original_order_no
        assert updated.created_at == original_created_at
        assert updated.supplier_id == master_data["alternate_supplier_id"]
        assert updated.supplier_id != original_supplier_id
        assert len(updated.items) == 1
        assert updated.items[0].product_id == master_data["mouse_id"]
        assert updated.total_amount == Decimal("106.50")
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 7
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0
        assert DatabaseOperationLog.query.filter_by(
            action="update_purchase_order_draft", status="success"
        ).count() == 1


def test_delete_purchase_order_draft_removes_order_and_items_without_side_effects(
    app, master_data
):
    with app.app_context():
        order = create_purchase_order_draft(
            master_data["supplier_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "80"}],
        )
        order_id = order.id

        delete_purchase_order_draft(order)

        assert db.session.get(PurchaseOrder, order_id) is None
        assert PurchaseOrderItem.query.count() == 0
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 7
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0


@pytest.mark.parametrize("status", ["pending_receipt", "completed"])
def test_update_purchase_order_draft_rejects_non_draft_without_mutation(
    app, master_data, status
):
    with app.app_context():
        order = create_purchase_order_draft(
            master_data["supplier_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "80"}],
        )
        order.status = status
        db.session.commit()
        order_id = order.id
        original_created_at = order.created_at
        original_order_no = order.order_no
        original_supplier_id = order.supplier_id
        original_item = (order.items[0].product_id, order.items[0].quantity, order.items[0].unit_price)
        original_stock = db.session.get(Product, master_data["keyboard_id"]).stock

        with pytest.raises(ValueError, match="草稿"):
            update_purchase_order_draft(
                order,
                master_data["alternate_supplier_id"],
                [{"product_id": master_data["mouse_id"], "quantity": 2, "unit_price": "35"}],
            )
        with pytest.raises(ValueError, match="草稿"):
            delete_purchase_order_draft(order)

        db.session.expire_all()
        unchanged = db.session.get(PurchaseOrder, order_id)
        assert unchanged.status == status
        assert unchanged.supplier_id == original_supplier_id
        assert unchanged.order_no == original_order_no
        assert unchanged.created_at == original_created_at
        assert unchanged.total_amount == Decimal("80.00")
        assert PurchaseOrderItem.query.count() == 1
        assert (unchanged.items[0].product_id, unchanged.items[0].quantity, unchanged.items[0].unit_price) == original_item
        assert db.session.get(Product, master_data["keyboard_id"]).stock == original_stock
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0


def test_update_purchase_order_draft_rolls_back_database_error_and_logs_action(
    app, master_data, monkeypatch
):
    with app.app_context():
        order = create_purchase_order_draft(
            master_data["supplier_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "80"}],
        )
        order_id = order.id
        original_commit = db.session.commit
        commit_calls = 0

        def fail_once_commit():
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 1:
                raise SQLAlchemyError("forced failure")
            return original_commit()

        rollback_calls = 0
        original_rollback = db.session.rollback

        def tracked_rollback():
            nonlocal rollback_calls
            rollback_calls += 1
            return original_rollback()

        monkeypatch.setattr(db.session, "commit", fail_once_commit)
        monkeypatch.setattr(db.session, "rollback", tracked_rollback)

        with pytest.raises(SQLAlchemyError, match="forced failure"):
            update_purchase_order_draft(
                order,
                master_data["alternate_supplier_id"],
                [{"product_id": master_data["mouse_id"], "quantity": 3, "unit_price": "35.50"}],
            )

        assert rollback_calls == 1
        unchanged = db.session.get(PurchaseOrder, order_id)
        assert unchanged.supplier_id == master_data["supplier_id"]
        assert unchanged.items[0].product_id == master_data["keyboard_id"]
        assert DatabaseOperationLog.query.filter_by(
            action="update_purchase_order_draft", status="error"
        ).count() == 1


def test_delete_purchase_order_draft_rolls_back_database_error_and_logs_action(
    app, master_data, monkeypatch
):
    with app.app_context():
        order = create_purchase_order_draft(
            master_data["supplier_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "80"}],
        )
        order_id = order.id
        original_commit = db.session.commit
        commit_calls = 0

        def fail_once_commit():
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 1:
                raise SQLAlchemyError("forced failure")
            return original_commit()

        rollback_calls = 0
        original_rollback = db.session.rollback

        def tracked_rollback():
            nonlocal rollback_calls
            rollback_calls += 1
            return original_rollback()

        monkeypatch.setattr(db.session, "commit", fail_once_commit)
        monkeypatch.setattr(db.session, "rollback", tracked_rollback)

        with pytest.raises(SQLAlchemyError, match="forced failure"):
            delete_purchase_order_draft(order)

        assert rollback_calls == 1
        assert db.session.get(PurchaseOrder, order_id) is not None
        assert PurchaseOrderItem.query.count() == 1
        assert DatabaseOperationLog.query.filter_by(
            action="delete_purchase_order_draft", status="error"
        ).count() == 1
