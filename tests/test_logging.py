import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.llm import DeepSeekLLMClient, LLMResponseError
from app import create_app
from models import (
    ApiCallLog,
    Customer,
    DatabaseOperationLog,
    Product,
    Supplier,
    db,
)
from services.orders import create_purchase_order_draft


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'logging.db'}",
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
        product = Product(
            name="机械键盘",
            sku="KB001",
            purchase_price=80,
            sale_price=120,
            stock=10,
        )
        db.session.add_all([supplier, customer, product])
        db.session.commit()
        return {"supplier_id": supplier.id, "product_id": product.id}


class FakeDeepSeekClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        if self.error:
            raise self.error
        return self.response


def text_response(content="ok"):
    return SimpleNamespace(
        id="req-log-001",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=[])
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=8,
            total_tokens=20,
        ),
    )


def test_order_creation_writes_database_operation_log(app, master_data):
    with app.app_context():
        order = create_purchase_order_draft(
            master_data["supplier_id"],
            [
                {
                    "product_id": master_data["product_id"],
                    "quantity": 2,
                    "unit_price": "78",
                }
            ],
            source="agent",
        )

        log = DatabaseOperationLog.query.one()
        assert log.source == "agent"
        assert log.action == "create_purchase_order_draft"
        assert log.entity_type == "PurchaseOrder"
        assert log.entity_id == order.order_no
        assert log.status == "success"
        assert json.loads(log.detail_json)["line_count"] == 1


def test_deepseek_call_writes_metadata_without_prompt_or_key(app):
    fake = FakeDeepSeekClient(text_response())
    client = DeepSeekLLMClient(
        api_key="sk-secret-value",
        model="deepseek-chat",
        client=fake,
    )

    with app.app_context():
        client.parse_message(
            "这是一段不应写入日志的业务文本",
            system_prompt="不应写入日志的系统提示",
            tools=[],
        )

        log = ApiCallLog.query.one()
        assert log.provider == "deepseek"
        assert log.model == "deepseek-chat"
        assert log.status == "success"
        assert log.request_id == "req-log-001"
        assert log.total_tokens == 20
        assert "sk-secret-value" not in log.detail_json
        assert "业务文本" not in log.detail_json
        assert "系统提示" not in log.detail_json


def test_failed_deepseek_call_is_logged(app):
    client = DeepSeekLLMClient(
        api_key="test-key",
        client=FakeDeepSeekClient(error=RuntimeError("upstream unavailable")),
    )

    with app.app_context():
        with pytest.raises(LLMResponseError):
            client.parse_message("查库存", system_prompt="系统", tools=[])

        log = ApiCallLog.query.one()
        assert log.status == "error"
        assert "upstream unavailable" in log.error_message


def test_log_pages_are_available(app):
    client = app.test_client()

    database_response = client.get("/logs/database")
    api_response = client.get("/logs/api")

    assert database_response.status_code == 200
    assert "数据库操作日志" in database_response.get_data(as_text=True)
    assert api_response.status_code == 200
    assert "API 调用日志" in api_response.get_data(as_text=True)
