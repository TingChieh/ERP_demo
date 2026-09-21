from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import create_app
from models import Customer, Product, SalesOrder, SalesOrderItem, db


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'dashboard.db'}",
        }
    )
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def replenishment_data(app):
    with app.app_context():
        customer = Customer(name="仪表盘客户", phone="")
        db.session.add(customer)
        db.session.flush()

        for index, name in enumerate(
            ["机械键盘", "人体工学鼠标", "显示器支架", "扩展坞", "网线", "摄像头"],
            start=1,
        ):
            product = Product(
                name=name,
                sku=f"LOW-STOCK-{index}",
                purchase_price=50,
                sale_price=80,
                stock=index,
            )
            order = SalesOrder(
                order_no=f"SO-DASHBOARD-{index}",
                customer_id=customer.id,
                status="completed",
                created_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            order.items.append(
                SalesOrderItem(product=product, quantity=14, unit_price=80)
            )
            db.session.add(order)

        db.session.add(
            Product(
                name="无销量商品",
                sku="NO-SALES",
                purchase_price=50,
                sale_price=80,
                stock=0,
            )
        )
        db.session.commit()


def test_dashboard_shows_at_most_five_real_low_stock_products(app, replenishment_data):
    response = app.test_client().get("/")
    body = response.get_data(as_text=True)

    assert "库存预警" in body
    assert body.count('data-replenishment-row="') == 5
    assert "机械键盘" in body
    assert "推荐补货" in body
    assert "无销量商品" not in body


def test_dashboard_warning_links_to_assistant_prompt(app, replenishment_data):
    body = app.test_client().get("/").get_data(as_text=True)

    assert "/assistant?prompt=" in body
    assert "分析机械键盘是否需要补货" in body
