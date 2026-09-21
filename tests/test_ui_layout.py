from pathlib import Path

import pytest

from app import create_app
from models import (
    AccountPayable,
    AccountReceivable,
    Customer,
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

    assert 'href="/products/"' in body
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


@pytest.mark.parametrize(
    "path,marker",
    [
        ("/", 'data-page-type="dashboard"'),
        ("/products", 'data-page-type="master-list"'),
        ("/products/new", 'data-page-type="master-form"'),
        ("/customers", 'data-page-type="master-list"'),
        ("/customers/new", 'data-page-type="master-form"'),
        ("/suppliers", 'data-page-type="master-list"'),
        ("/suppliers/new", 'data-page-type="master-form"'),
    ],
)
def test_dashboard_and_master_data_pages_use_page_types(app, path, marker):
    body = app.test_client().get(path).get_data(as_text=True)

    assert marker in body
    assert 'class="surface-card' in body


@pytest.mark.parametrize(
    "path,marker",
    [
        ("/purchase-orders", 'data-page-type="order-list"'),
        ("/purchase-orders/new", 'data-page-type="order-form"'),
        ("/sales-orders", 'data-page-type="order-list"'),
        ("/sales-orders/new", 'data-page-type="order-form"'),
        ("/receivables", 'data-page-type="settlement-list"'),
        ("/payables", 'data-page-type="settlement-list"'),
        ("/logs/database", 'data-page-type="log-list"'),
        ("/logs/api", 'data-page-type="log-list"'),
    ],
)
def test_business_pages_use_semantic_page_types(app, path, marker):
    body = app.test_client().get(path).get_data(as_text=True)

    assert marker in body
    assert 'class="surface-card' in body


def test_assistant_keeps_the_javascript_contract(app):
    response = app.test_client().get("/assistant")
    body = response.get_data(as_text=True)

    assert 'id="assistant-chat"' in body
    assert 'id="assistant-form"' in body
    assert 'id="assistant-input"' in body
    assert "assistant.js" in body

    assistant_js = Path("static/js/assistant.js").read_text(encoding="utf-8")
    assert 'confirmPreview(response.confirmation_token, "cancel")' in assistant_js
    assert 'fetch("/assistant/confirm"' in assistant_js
    assert 'JSON.stringify({ confirmation_token: token, action })' in assistant_js


def test_assistant_is_a_surface_page_with_examples(app):
    body = app.test_client().get("/assistant").get_data(as_text=True)

    assert 'data-page-type="assistant"' in body
    assert 'class="assistant-page surface-page' in body
    assert 'class="assistant-example chip' in body


def test_narrow_tables_keep_columns_readable_with_horizontal_scrolling():
    css = Path("static/css/style.css").read_text(encoding="utf-8")

    assert ".table-responsive { overflow-x: auto; }" in css
    assert ".table-responsive > .table { min-width: 680px; }" in css


def test_business_forms_keep_existing_post_contracts(app):
    client = app.test_client()

    for path in ("/products/new", "/customers/new", "/suppliers/new", "/purchase-orders/new"):
        body = client.get(path).get_data(as_text=True)
        assert '<form method="post">' in body

    with app.app_context():
        supplier = Supplier(name="QA Supplier", phone="")
        customer = Customer(name="QA Customer", phone="")
        product = Product(
            name="QA Product", sku="QA001", purchase_price=40, sale_price=69, stock=3
        )
        db.session.add_all([supplier, customer, product])
        db.session.flush()
        purchase_order = PurchaseOrder(
            order_no="PO-QA", supplier_id=supplier.id, status="draft", total_amount=40
        )
        sales_order = SalesOrder(
            order_no="SO-QA", customer_id=customer.id, status="completed", total_amount=69
        )
        db.session.add_all([purchase_order, sales_order])
        db.session.flush()
        receivable = AccountReceivable(
            sales_order_id=sales_order.id,
            customer_id=customer.id,
            amount=69,
            status="unpaid",
        )
        payable = AccountPayable(
            purchase_order_id=purchase_order.id,
            supplier_id=supplier.id,
            amount=40,
            status="unpaid",
        )
        db.session.add_all([receivable, payable])
        db.session.commit()
        purchase_order_id = purchase_order.id
        receivable_id = receivable.id
        payable_id = payable.id

    assert (
        f'action="/purchase-orders/{purchase_order_id}/submit"'
        in client.get(f"/purchase-orders/{purchase_order_id}").get_data(as_text=True)
    )
    assert (
        f'action="/receivables/{receivable_id}/receive-payment"'
        in client.get("/receivables").get_data(as_text=True)
    )
    assert (
        f'action="/payables/{payable_id}/pay"'
        in client.get("/payables").get_data(as_text=True)
    )
