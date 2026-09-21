from pathlib import Path

import pytest

from app import create_app
from models import Customer, Product, Supplier, db


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'master_data.db'}",
        }
    )

    with app.app_context():
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_product_list_page_returns_200(app):
    response = app.test_client().get("/products")

    assert response.status_code == 200
    assert "商品管理" in response.get_data(as_text=True)


def test_can_create_product_with_zero_stock(app):
    response = app.test_client().post(
        "/products/new",
        data={
            "name": "机械键盘",
            "sku": "KB001",
            "purchase_price": "80",
            "sale_price": "120",
        },
    )

    assert response.status_code == 302

    with app.app_context():
        product = Product.query.filter_by(sku="KB001").one()
        assert product.name == "机械键盘"
        assert product.stock == 0


def test_duplicate_sku_cannot_create_product(app):
    client = app.test_client()
    data = {
        "name": "机械键盘",
        "sku": "KB001",
        "purchase_price": "80",
        "sale_price": "120",
    }

    assert client.post("/products/new", data=data).status_code == 302
    response = client.post("/products/new", data={**data, "name": "另一款键盘"})

    assert response.status_code == 200
    assert "SKU 已存在" in response.get_data(as_text=True)

    with app.app_context():
        assert Product.query.count() == 1


def test_product_edit_form_does_not_expose_stock_field(app):
    with app.app_context():
        product = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=8
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

    response = app.test_client().get(f"/products/{product_id}/edit")

    assert response.status_code == 200
    assert 'name="stock"' not in response.get_data(as_text=True)


def test_product_edit_ignores_submitted_stock(app):
    with app.app_context():
        product = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=8
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

    response = app.test_client().post(
        f"/products/{product_id}/edit",
        data={
            "name": "升级版机械键盘",
            "sku": "KB001",
            "purchase_price": "85",
            "sale_price": "130",
            "stock": "999",
        },
    )

    assert response.status_code == 302

    with app.app_context():
        product = db.session.get(Product, product_id)
        assert product.name == "升级版机械键盘"
        assert product.stock == 8


def test_can_create_supplier(app):
    response = app.test_client().post(
        "/suppliers/new", data={"name": "南京键盘供应商", "phone": "025-12345678"}
    )

    assert response.status_code == 302

    with app.app_context():
        supplier = Supplier.query.one()
        assert supplier.name == "南京键盘供应商"


def test_can_create_customer(app):
    response = app.test_client().post(
        "/customers/new", data={"name": "大圣科技", "phone": "025-87654321"}
    )

    assert response.status_code == 302

    with app.app_context():
        customer = Customer.query.one()
        assert customer.name == "大圣科技"
