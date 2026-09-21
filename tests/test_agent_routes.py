from pathlib import Path

import pytest

from agent.llm import MockLLMClient
from agent.schemas import ToolCall
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
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'agent_routes.db'}",
            "AGENT_LLM_CLIENT": MockLLMClient([]),
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
        customer = Customer(name="大圣科技", phone="")
        keyboard = Product(
            name="机械键盘",
            sku="KB001",
            purchase_price=80,
            sale_price=120,
            stock=80,
        )
        db.session.add_all([supplier, customer, keyboard])
        db.session.commit()
        return {
            "supplier_id": supplier.id,
            "customer_id": customer.id,
            "product_id": keyboard.id,
        }


def set_llm(app, *responses):
    app.config["AGENT_LLM_CLIENT"] = MockLLMClient(list(responses))


def purchase_call(product_name="机械键盘"):
    return ToolCall(
        name="prepare_purchase_order",
        arguments={
            "supplier_name": "南京键盘供应商",
            "items": [
                {
                    "product_name": product_name,
                    "sku": None,
                    "quantity": 2,
                    "unit_price": 78,
                }
            ],
        },
    )


def sales_call():
    return ToolCall(
        name="prepare_sales_order",
        arguments={
            "customer_name": "大圣科技",
            "items": [
                {
                    "product_name": "机械键盘",
                    "sku": None,
                    "quantity": 100,
                    "unit_price": 120,
                }
            ],
        },
    )


def test_assistant_page_returns_200(app):
    response = app.test_client().get("/assistant")

    assert response.status_code == 200
    assert "AI ERP Assistant" in response.get_data(as_text=True)
    assert "查一下机械键盘库存" in response.get_data(as_text=True)


def test_assistant_message_returns_verified_inventory_result(app, master_data):
    set_llm(
        app,
        ToolCall(
            name="get_inventory",
            arguments={"product_name": "机械键盘", "sku": None},
        ),
    )

    response = app.test_client().post(
        "/assistant/message", json={"message": "查一下机械键盘库存"}
    )

    assert response.status_code == 200
    assert response.json["type"] == "message"
    assert "80" in response.json["content"]


def test_purchase_message_returns_preview_without_creating_order(app, master_data):
    set_llm(app, purchase_call())

    response = app.test_client().post(
        "/assistant/message", json={"message": "向南京键盘供应商采购 2 个机械键盘"}
    )

    assert response.status_code == 200
    assert response.json["type"] == "confirmation"
    assert response.json["preview"]["total_amount"] == "156.00"
    with app.app_context():
        assert PurchaseOrder.query.count() == 0
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0


def test_purchase_confirmation_creates_only_after_explicit_confirm(app, master_data):
    set_llm(app, purchase_call())
    client = app.test_client()

    preview_response = client.post(
        "/assistant/message", json={"message": "生成采购预览"}
    )
    token = preview_response.json["confirmation_token"]
    confirm_response = client.post(
        "/assistant/confirm",
        json={"confirmation_token": token, "action": "confirm"},
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json["type"] == "message"
    with app.app_context():
        assert PurchaseOrder.query.count() == 1
        assert PurchaseOrder.query.one().status == "draft"
        assert InventoryTransaction.query.count() == 0
        assert AccountPayable.query.count() == 0


def test_cancelled_purchase_preview_does_not_create_order(app, master_data):
    set_llm(app, purchase_call())
    client = app.test_client()
    preview_response = client.post(
        "/assistant/message", json={"message": "生成采购预览"}
    )

    response = client.post(
        "/assistant/confirm",
        json={
            "confirmation_token": preview_response.json["confirmation_token"],
            "action": "cancel",
        },
    )

    assert response.status_code == 200
    assert response.json["type"] == "message"
    with app.app_context():
        assert PurchaseOrder.query.count() == 0


def test_invalid_confirmation_token_does_not_create_order(app, master_data):
    response = app.test_client().post(
        "/assistant/confirm",
        json={"confirmation_token": "forged", "action": "confirm"},
    )

    assert response.status_code == 400
    assert response.json["type"] == "error"
    with app.app_context():
        assert PurchaseOrder.query.count() == 0


def test_sales_confirmation_allows_insufficient_stock_and_creates_no_side_effects(
    app, master_data
):
    set_llm(app, sales_call())
    client = app.test_client()
    preview_response = client.post(
        "/assistant/message", json={"message": "给大圣科技销售 100 个机械键盘"}
    )

    confirm_response = client.post(
        "/assistant/confirm",
        json={
            "confirmation_token": preview_response.json["confirmation_token"],
            "action": "confirm",
        },
    )

    assert confirm_response.status_code == 200
    with app.app_context():
        assert SalesOrder.query.count() == 1
        assert SalesOrder.query.one().status == "draft"
        assert db.session.get(Product, master_data["product_id"]).stock == 80
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0


@pytest.mark.parametrize("message", ["把 PO20260921001 入库", "把 SO20260921001 发货", "确认收款", "确认付款"])
def test_assistant_refuses_high_risk_operations_without_mutation(app, message):
    response = app.test_client().post("/assistant/message", json={"message": message})

    assert response.status_code == 200
    assert response.json["type"] == "error"
    assert "暂不支持" in response.json["message"]
    with app.app_context():
        assert PurchaseOrder.query.count() == 0
        assert SalesOrder.query.count() == 0
        assert InventoryTransaction.query.count() == 0
        assert AccountReceivable.query.count() == 0
        assert AccountPayable.query.count() == 0
