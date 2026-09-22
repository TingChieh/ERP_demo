from pathlib import Path
from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.datastructures import MultiDict

from app import create_app
from models import (
    AccountReceivable,
    Customer,
    DatabaseOperationLog,
    InventoryTransaction,
    Product,
    SalesOrder,
    SalesOrderItem,
    db,
)
from services.orders import (
    create_sales_order_draft,
    delete_sales_order_draft,
    update_sales_order_draft,
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
        alternate_customer = Customer(name="齐天科技", phone="")
        keyboard = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=5
        )
        mouse = Product(
            name="鼠标", sku="MS001", purchase_price=40, sale_price=69, stock=20
        )
        db.session.add_all([customer, alternate_customer, keyboard, mouse])
        db.session.commit()
        return {
            "customer_id": customer.id,
            "alternate_customer_id": alternate_customer.id,
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


def test_sales_draft_edit_get_prefills_current_values(app, master_data):
    client = app.test_client()
    client.post(
        "/sales-orders/new",
        data=sales_form(
            master_data["customer_id"],
            [(master_data["keyboard_id"], 2, "120")],
        ),
    )
    with app.app_context():
        order_id = SalesOrder.query.one().id

    response = client.get(f"/sales-orders/{order_id}/edit")

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert f'<option value="{master_data["customer_id"]}" selected>' in html
    assert (
        f'name="product_ids" value="{master_data["keyboard_id"]}" checked'
        in html
    )
    assert (
        f'name="quantity_{master_data["keyboard_id"]}" type="number" '
        'min="1" step="1" value="2"'
        in html
    )
    assert (
        f'name="unit_price_{master_data["keyboard_id"]}" type="number" '
        'min="0" step="0.01" value="120"'
        in html
    )
    assert f'<form method="post" action="/sales-orders/{order_id}/edit">' in html
    assert "编辑销售订单" in html


def test_sales_draft_edit_replaces_customer_lines_and_total_without_side_effects(
    app, master_data
):
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
        initial_stock = db.session.get(Product, master_data["keyboard_id"]).stock

    response = client.post(
        f"/sales-orders/{order_id}/edit",
        data=sales_form(
            master_data["alternate_customer_id"],
            [(master_data["mouse_id"], 3, "65.50")],
        ),
    )

    assert response.status_code == 302
    with app.app_context():
        order = db.session.get(SalesOrder, order_id)
        assert order.status == "draft"
        assert order.customer_id == master_data["alternate_customer_id"]
        assert order.total_amount == Decimal("196.50")
        assert [(item.product_id, item.quantity, item.unit_price) for item in order.items] == [
            (master_data["mouse_id"], 3, Decimal("65.50"))
        ]
        assert db.session.get(Product, master_data["keyboard_id"]).stock == initial_stock
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


def test_sales_draft_edit_validation_error_echoes_submitted_data_without_mutation(
    app, master_data
):
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
        order_id = order.id
        original = (order.customer_id, order.total_amount, order.items[0].product_id)

    response = client.post(
        f"/sales-orders/{order_id}/edit",
        data=sales_form(
            master_data["alternate_customer_id"],
            [(master_data["mouse_id"], -3, "65.50")],
        ),
    )

    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "鼠标的数量必须大于 0" in html
    assert f'<option value="{master_data["alternate_customer_id"]}" selected>' in html
    assert f'name="product_ids" value="{master_data["mouse_id"]}" checked' in html
    with app.app_context():
        order = db.session.get(SalesOrder, order_id)
        assert (order.customer_id, order.total_amount, order.items[0].product_id) == original


def test_sales_draft_delete_removes_order_and_items(app, master_data):
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

    response = client.post(f"/sales-orders/{order_id}/delete")

    assert response.status_code == 302
    with app.app_context():
        assert SalesOrder.query.count() == 0
        assert SalesOrderItem.query.count() == 0
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


@pytest.mark.parametrize("status", ["pending_shipment", "completed"])
def test_sales_non_draft_edit_and_delete_return_400(app, master_data, status):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "120"}],
        )
        order.status = status
        db.session.commit()
        order_id = order.id

    client = app.test_client()
    assert client.get(f"/sales-orders/{order_id}/edit").status_code == 400
    assert client.post(
        f"/sales-orders/{order_id}/edit",
        data=sales_form(
            master_data["alternate_customer_id"],
            [(master_data["mouse_id"], 2, "65")],
        ),
    ).status_code == 400
    assert client.post(f"/sales-orders/{order_id}/delete").status_code == 400


@pytest.mark.parametrize("status", ["draft", "pending_shipment", "completed"])
def test_sales_detail_shows_edit_delete_controls_only_for_drafts(
    app, master_data, status
):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "120"}],
        )
        order.status = status
        db.session.commit()
        order_id = order.id

    html = app.test_client().get(f"/sales-orders/{order_id}").get_data(as_text=True)

    if status == "draft":
        assert f"/sales-orders/{order_id}/edit" in html
        assert f'<form method="post" action="/sales-orders/{order_id}/delete"' in html
        assert "确定删除这份销售草稿吗？" in html
    else:
        assert f"/sales-orders/{order_id}/edit" not in html
        assert f"/sales-orders/{order_id}/delete" not in html


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


def test_shared_sales_service_creates_validated_draft(app, master_data):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [
                {
                    "product_id": master_data["keyboard_id"],
                    "quantity": 2,
                    "unit_price": Decimal("120.00"),
                }
            ],
        )

        assert order.status == "draft"
        assert order.total_amount == Decimal("240.00")
        assert order.items[0].product_id == master_data["keyboard_id"]
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


def test_shared_sales_service_rejects_duplicate_products_without_order(
    app, master_data
):
    with app.app_context():
        with pytest.raises(ValueError, match="不能重复"):
            create_sales_order_draft(
                master_data["customer_id"],
                [
                    {
                        "product_id": master_data["keyboard_id"],
                        "quantity": 1,
                        "unit_price": Decimal("120.00"),
                    },
                    {
                        "product_id": master_data["keyboard_id"],
                        "quantity": 2,
                        "unit_price": Decimal("119.00"),
                    },
                ],
            )

        assert SalesOrder.query.count() == 0


def test_update_sales_order_draft_replaces_lines_and_total(app, master_data):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "120"}],
        )
        original_order_no = order.order_no
        original_created_at = order.created_at
        original_customer_id = order.customer_id

        updated = update_sales_order_draft(
            order,
            master_data["alternate_customer_id"],
            [{"product_id": master_data["mouse_id"], "quantity": 3, "unit_price": "35.50"}],
        )

        assert updated.status == "draft"
        assert updated.order_no == original_order_no
        assert updated.created_at == original_created_at
        assert updated.customer_id == master_data["alternate_customer_id"]
        assert updated.customer_id != original_customer_id
        assert len(updated.items) == 1
        assert updated.items[0].product_id == master_data["mouse_id"]
        assert updated.total_amount == Decimal("106.50")
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 5
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0
        assert DatabaseOperationLog.query.filter_by(
            action="update_sales_order_draft", status="success"
        ).count() == 1


def test_update_sales_order_draft_keeps_and_replaces_lines(app, master_data):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [
                {
                    "product_id": master_data["keyboard_id"],
                    "quantity": 1,
                    "unit_price": "120",
                },
                {
                    "product_id": master_data["mouse_id"],
                    "quantity": 2,
                    "unit_price": "65",
                },
            ],
        )
        monitor = Product(
            name="显示器", sku="MN001", purchase_price=500, sale_price=800, stock=4
        )
        db.session.add(monitor)
        db.session.commit()
        original_order_no = order.order_no
        original_created_at = order.created_at

        updated = update_sales_order_draft(
            order,
            master_data["alternate_customer_id"],
            [
                {
                    "product_id": master_data["keyboard_id"],
                    "quantity": 3,
                    "unit_price": "119.50",
                },
                {"product_id": monitor.id, "quantity": 1, "unit_price": "800"},
            ],
        )

        assert updated.status == "draft"
        assert updated.order_no == original_order_no
        assert updated.created_at == original_created_at
        assert updated.customer_id == master_data["alternate_customer_id"]
        assert updated.total_amount == Decimal("1158.50")
        assert sorted(
            (item.product_id, item.quantity, item.unit_price) for item in updated.items
        ) == sorted(
            [
                (master_data["keyboard_id"], 3, Decimal("119.50")),
                (monitor.id, 1, Decimal("800")),
            ]
        )
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 5
        assert db.session.get(Product, master_data["mouse_id"]).stock == 20
        assert db.session.get(Product, monitor.id).stock == 4
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


def test_delete_sales_order_draft_removes_order_and_items_without_side_effects(
    app, master_data
):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "120"}],
        )
        order_id = order.id

        delete_sales_order_draft(order)

        assert db.session.get(SalesOrder, order_id) is None
        assert SalesOrderItem.query.count() == 0
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 5
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


@pytest.mark.parametrize("status", ["pending_shipment", "completed"])
def test_update_sales_order_draft_rejects_non_draft_without_mutation(
    app, master_data, status
):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "120"}],
        )
        order.status = status
        db.session.commit()
        order_id = order.id
        original_created_at = order.created_at
        original_order_no = order.order_no
        original_customer_id = order.customer_id
        original_item = (order.items[0].product_id, order.items[0].quantity, order.items[0].unit_price)
        original_stock = db.session.get(Product, master_data["keyboard_id"]).stock

        with pytest.raises(ValueError, match="草稿"):
            update_sales_order_draft(
                order,
                master_data["alternate_customer_id"],
                [{"product_id": master_data["mouse_id"], "quantity": 2, "unit_price": "35"}],
            )
        with pytest.raises(ValueError, match="草稿"):
            delete_sales_order_draft(order)

        db.session.expire_all()
        unchanged = db.session.get(SalesOrder, order_id)
        assert unchanged.status == status
        assert unchanged.customer_id == original_customer_id
        assert unchanged.order_no == original_order_no
        assert unchanged.created_at == original_created_at
        assert unchanged.total_amount == Decimal("120.00")
        assert SalesOrderItem.query.count() == 1
        assert (unchanged.items[0].product_id, unchanged.items[0].quantity, unchanged.items[0].unit_price) == original_item
        assert db.session.get(Product, master_data["keyboard_id"]).stock == original_stock
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


def test_update_sales_order_draft_rolls_back_database_error_and_logs_action(
    app, master_data, monkeypatch
):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "120"}],
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
            update_sales_order_draft(
                order,
                master_data["alternate_customer_id"],
                [{"product_id": master_data["mouse_id"], "quantity": 3, "unit_price": "35.50"}],
            )

        assert rollback_calls == 1
        unchanged = db.session.get(SalesOrder, order_id)
        assert unchanged.customer_id == master_data["customer_id"]
        assert unchanged.items[0].product_id == master_data["keyboard_id"]
        assert DatabaseOperationLog.query.filter_by(
            action="update_sales_order_draft", status="error"
        ).count() == 1


def test_delete_sales_order_draft_rolls_back_database_error_and_logs_action(
    app, master_data, monkeypatch
):
    with app.app_context():
        order = create_sales_order_draft(
            master_data["customer_id"],
            [{"product_id": master_data["keyboard_id"], "quantity": 1, "unit_price": "120"}],
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
            delete_sales_order_draft(order)

        assert rollback_calls == 1
        assert db.session.get(SalesOrder, order_id) is not None
        assert SalesOrderItem.query.count() == 1
        assert DatabaseOperationLog.query.filter_by(
            action="delete_sales_order_draft", status="error"
        ).count() == 1
