from pathlib import Path

import pytest

from app import create_app
from models import db


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'ui.db'}",
        }
    )
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize(
    "path,endpoint",
    [
        ("/", "dashboard"),
        ("/assistant", "assistant.assistant_page"),
        ("/products", "products.list_products"),
        ("/products/new", "products.new_product"),
        ("/customers", "customers.list_customers"),
        ("/suppliers", "suppliers.list_suppliers"),
        ("/purchase-orders", "purchase_orders.list_purchase_orders"),
        ("/purchase-orders/new", "purchase_orders.new_purchase_order"),
        ("/sales-orders", "sales_orders.list_sales_orders"),
        ("/sales-orders/new", "sales_orders.new_sales_order"),
        ("/receivables", "settlements.list_receivables"),
        ("/payables", "settlements.list_payables"),
        ("/logs/database", "logs.database_logs"),
        ("/logs/api", "logs.api_logs"),
    ],
)
def test_primary_pages_render_the_shared_shell(app, path, endpoint):
    response = app.test_client().get(path)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'data-app-shell="erp"' in body
    assert f'data-page="{endpoint}"' in body


def test_current_page_is_the_only_active_navigation_link(app):
    response = app.test_client().get("/products")
    body = response.get_data(as_text=True)

    assert 'href="/products"' in body
    assert 'data-nav-endpoint="products.list_products"' in body
    assert body.count('aria-current="page"') == 1
    assert 'aria-current="page"' in body


def test_dashboard_keeps_all_existing_metric_values(app):
    response = app.test_client().get("/")
    body = response.get_data(as_text=True)

    assert "商品数量" in body
    assert "当前总库存" in body
    assert "未收应收账款" in body
    assert "销售总额（已完成出库）" in body


def test_assistant_keeps_the_javascript_contract(app):
    response = app.test_client().get("/assistant")
    body = response.get_data(as_text=True)

    assert 'id="assistant-chat"' in body
    assert 'id="assistant-form"' in body
    assert 'id="assistant-input"' in body
    assert "assistant.js" in body
