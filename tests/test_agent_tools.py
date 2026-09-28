from decimal import Decimal
from pathlib import Path

import pytest

from app import create_app
from models import (
    AccountReceivable,
    Customer,
    Product,
    PurchaseOrder,
    SalesOrder,
    Supplier,
    db,
)
from agent.tools import (
    confirm_purchase_order,
    confirm_sales_order,
    get_inventory,
    get_unpaid_receivables,
    prepare_purchase_order,
    prepare_sales_order,
)


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'agent_tools.db'}",
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
        customer = Customer(name="xx科技", phone="")
        products = [
            Product(
                name="机械键盘",
                sku="KB001",
                purchase_price=80,
                sale_price=120,
                stock=80,
            ),
            Product(
                name="薄膜键盘",
                sku="KB002",
                purchase_price=50,
                sale_price=75,
                stock=20,
            ),
            Product(
                name="蓝牙键盘",
                sku="KB003",
                purchase_price=90,
                sale_price=150,
                stock=10,
            ),
            Product(
                name="鼠标",
                sku="MS001",
                purchase_price=40,
                sale_price=69,
                stock=3,
            ),
        ]
        db.session.add_all([supplier, customer, *products])
        db.session.commit()
        return {
            "supplier_id": supplier.id,
            "customer_id": customer.id,
            "keyboard_id": products[0].id,
            "mouse_id": products[3].id,
        }


def test_get_inventory_returns_real_product_stock(app, master_data):
    with app.app_context():
        response = get_inventory(product_name="机械键盘")

        assert response.type == "message"
        assert "80" in response.content
        assert response.data["sku"] == "KB001"
        assert response.data["stock"] == 80


def test_get_inventory_does_not_fabricate_missing_product(app, master_data):
    with app.app_context():
        response = get_inventory(product_name="不存在的商品")

        assert response.type == "clarification"
        assert "不存在" in response.message
        assert response.data is None


def test_get_inventory_returns_candidates_for_ambiguous_product_name(
    app, master_data
):
    with app.app_context():
        response = get_inventory(product_name="键盘")

        assert response.type == "clarification"
        assert len(response.candidates) == 3
        assert {candidate["sku"] for candidate in response.candidates} == {
            "KB001",
            "KB002",
            "KB003",
        }


def test_purchase_preview_recalculates_total_and_does_not_create_order(
    app, master_data
):
    with app.app_context():
        response = prepare_purchase_order(
            supplier_name="南京键盘供应商",
            items=[
                {
                    "product_name": "机械键盘",
                    "quantity": 100,
                    "unit_price": "78",
                }
            ],
            total_amount="1",
        )

        assert response.type == "confirmation"
        assert response.preview["total_amount"] == "7800.00"
        assert response.payload["supplier_id"] == master_data["supplier_id"]
        assert PurchaseOrder.query.count() == 0


def test_purchase_preview_uses_default_purchase_price(app, master_data):
    with app.app_context():
        response = prepare_purchase_order(
            supplier_name="南京键盘供应商",
            items=[{"product_name": "机械键盘", "quantity": 2}],
        )

        assert response.type == "confirmation"
        assert response.preview["items"][0]["unit_price"] == "80.00"
        assert response.preview["items"][0]["price_source"] == "default_purchase_price"


def test_purchase_confirmation_creates_draft_without_inventory_or_payable(
    app, master_data
):
    with app.app_context():
        preview = prepare_purchase_order(
            supplier_name="南京键盘供应商",
            items=[{"product_name": "机械键盘", "quantity": 2, "unit_price": 78}],
        )
        response = confirm_purchase_order(preview.payload)

        assert response.type == "message"
        assert PurchaseOrder.query.count() == 1
        assert PurchaseOrder.query.one().status == "draft"
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 80


def test_invalid_purchase_entities_do_not_create_order(app, master_data):
    with app.app_context():
        missing_supplier = prepare_purchase_order(
            supplier_name="不存在的供应商",
            items=[{"product_name": "机械键盘", "quantity": 1, "unit_price": 80}],
        )
        missing_product = prepare_purchase_order(
            supplier_name="南京键盘供应商",
            items=[{"product_name": "不存在的商品", "quantity": 1, "unit_price": 80}],
        )

        assert missing_supplier.type == "clarification"
        assert missing_product.type == "clarification"
        assert PurchaseOrder.query.count() == 0


def test_sales_preview_uses_default_price_and_allows_insufficient_stock(
    app, master_data
):
    with app.app_context():
        response = prepare_sales_order(
            customer_name="xx科技",
            items=[{"product_name": "机械键盘", "quantity": 100}],
        )

        assert response.type == "confirmation"
        assert response.preview["items"][0]["unit_price"] == "120.00"
        assert response.preview["items"][0]["price_source"] == "default_sale_price"
        assert SalesOrder.query.count() == 0


def test_sales_confirmation_creates_draft_without_inventory_or_receivable(
    app, master_data
):
    with app.app_context():
        preview = prepare_sales_order(
            customer_name="xx科技",
            items=[{"product_name": "机械键盘", "quantity": 100, "unit_price": 120}],
        )
        response = confirm_sales_order(preview.payload)

        assert response.type == "message"
        assert SalesOrder.query.count() == 1
        assert SalesOrder.query.one().status == "draft"
        assert db.session.get(Product, master_data["keyboard_id"]).stock == 80


def test_unpaid_receivables_can_query_all_and_by_customer(app, master_data):
    with app.app_context():
        order = SalesOrder(
            order_no="SO20260921001",
            customer_id=master_data["customer_id"],
            status="completed",
            total_amount=Decimal("240.00"),
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(
            AccountReceivable(
                sales_order_id=order.id,
                customer_id=master_data["customer_id"],
                amount=Decimal("240.00"),
                status="unpaid",
            )
        )
        other_customer = Customer(name="另一家科技", phone="")
        db.session.add(other_customer)
        db.session.flush()
        other_order = SalesOrder(
            order_no="SO20260921002",
            customer_id=other_customer.id,
            status="completed",
            total_amount=Decimal("310.00"),
        )
        db.session.add(other_order)
        db.session.flush()
        db.session.add(
            AccountReceivable(
                sales_order_id=other_order.id,
                customer_id=other_customer.id,
                amount=Decimal("310.00"),
                status="unpaid",
            )
        )
        paid_order = SalesOrder(
            order_no="SO20260921003",
            customer_id=other_customer.id,
            status="completed",
            total_amount=Decimal("50.00"),
        )
        db.session.add(paid_order)
        db.session.flush()
        db.session.add(
            AccountReceivable(
                sales_order_id=paid_order.id,
                customer_id=other_customer.id,
                amount=Decimal("50.00"),
                status="paid",
            )
        )
        db.session.commit()

        all_response = get_unpaid_receivables()
        customer_response = get_unpaid_receivables(customer_name="xx科技")

        assert all_response.type == "message"
        assert all_response.data["total_amount"] == "550.00"
        assert len(all_response.data["items"]) == 2
        assert {item["customer"] for item in all_response.data["items"]} == {
            "xx科技",
            "另一家科技",
        }
        assert all_response.data["items"][0]["receivable_id"]
        assert all_response.data["items"][0]["sales_order_id"]
        assert all_response.data["items"][0]["sales_order_no"]
        assert all_response.data["items"][0]["created_at"]
        assert "xx科技" in all_response.content
        assert "240.00" in all_response.content
        assert customer_response.data["total_amount"] == "240.00"
        assert len(customer_response.data["items"]) == 1
        assert customer_response.data["items"][0]["customer"] == "xx科技"


def test_unpaid_receivables_with_no_records_returns_empty_read_only_result(
    app, master_data
):
    with app.app_context():
        response = get_unpaid_receivables()

        assert response.type == "message"
        assert response.content == "目前没有未收应收账款。"
        assert response.data == {
            "query_type": "unpaid_receivables",
            "total_amount": "0.00",
            "items": [],
        }


def test_missing_customer_blocks_sales_confirmation(app, master_data):
    with app.app_context():
        response = prepare_sales_order(
            customer_name="不存在的客户",
            items=[{"product_name": "机械键盘", "quantity": 1, "unit_price": 120}],
        )

        assert response.type == "clarification"
        assert SalesOrder.query.count() == 0
