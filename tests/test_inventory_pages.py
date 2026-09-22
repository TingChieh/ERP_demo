from pathlib import Path

import pytest

from app import create_app
from models import (
    Customer,
    InventoryTransaction,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    SalesOrder,
    SalesOrderItem,
    Supplier,
    db,
)


@pytest.fixture()
def app(tmp_path: Path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'inventory.db'}",
        }
    )
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


def seed_inventory_data(app):
    with app.app_context():
        supplier = Supplier(name="供应商 A", phone="")
        customer = Customer(name="客户 A", phone="")
        keyboard = Product(
            name="机械键盘", sku="KB001", purchase_price=80, sale_price=120, stock=8
        )
        mouse = Product(
            name="鼠标", sku="MS001", purchase_price=40, sale_price=69, stock=0
        )
        db.session.add_all([supplier, customer, keyboard, mouse])
        db.session.flush()
        pending_purchase = PurchaseOrder(
            order_no="PO-PENDING",
            supplier_id=supplier.id,
            status="pending_receipt",
            total_amount=160,
        )
        completed_purchase = PurchaseOrder(
            order_no="PO-COMPLETED",
            supplier_id=supplier.id,
            status="completed",
            total_amount=80,
        )
        pending_sales = SalesOrder(
            order_no="SO-PENDING",
            customer_id=customer.id,
            status="pending_shipment",
            total_amount=240,
        )
        completed_sales = SalesOrder(
            order_no="SO-COMPLETED",
            customer_id=customer.id,
            status="completed",
            total_amount=120,
        )
        db.session.add_all(
            [pending_purchase, completed_purchase, pending_sales, completed_sales]
        )
        db.session.flush()
        db.session.add_all(
            [
                PurchaseOrderItem(
                    purchase_order=pending_purchase,
                    product_id=keyboard.id,
                    quantity=2,
                    unit_price=80,
                ),
                SalesOrderItem(
                    sales_order=pending_sales,
                    product_id=keyboard.id,
                    quantity=2,
                    unit_price=120,
                ),
                InventoryTransaction(
                    product_id=keyboard.id,
                    type="inbound",
                    quantity=10,
                    related_order_no="PO-COMPLETED",
                    balance_after=8,
                ),
                InventoryTransaction(
                    product_id=keyboard.id,
                    type="outbound",
                    quantity=2,
                    related_order_no="SO-COMPLETED",
                    balance_after=8,
                ),
            ]
        )
        db.session.commit()
        return {
            "pending_purchase_id": pending_purchase.id,
            "pending_sales_id": pending_sales.id,
        }


@pytest.mark.parametrize(
    "path,endpoint,title,empty_text",
    [
        ("/purchase-receipts", "inventory.purchase_receipts", "采购入库", "暂无待入库采购订单"),
        ("/sales-shipments", "inventory.sales_shipments", "销售出库", "暂无待出库销售订单"),
        ("/inventory", "inventory.current_inventory", "当前库存", "暂无商品库存数据"),
        ("/inventory/transactions", "inventory.inventory_transactions", "库存流水", "暂无库存流水记录"),
    ],
)
def test_inventory_pages_render_empty_states(app, path, endpoint, title, empty_text):
    response = app.test_client().get(path)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'data-page="{endpoint}"' in body
    assert title in body
    assert empty_text in body


def test_purchase_receipts_only_show_pending_orders_and_link_to_detail(app):
    ids = seed_inventory_data(app)
    body = app.test_client().get("/purchase-receipts").get_data(as_text=True)

    assert "PO-PENDING" in body
    assert "PO-COMPLETED" not in body
    assert f'/purchase-orders/{ids["pending_purchase_id"]}' in body


def test_sales_shipments_only_show_pending_orders_and_link_to_detail(app):
    ids = seed_inventory_data(app)
    body = app.test_client().get("/sales-shipments").get_data(as_text=True)

    assert "SO-PENDING" in body
    assert "SO-COMPLETED" not in body
    assert f'/sales-orders/{ids["pending_sales_id"]}' in body


def test_current_inventory_shows_stock_and_status_for_each_product(app):
    seed_inventory_data(app)
    body = app.test_client().get("/inventory").get_data(as_text=True)

    assert "机械键盘" in body
    assert "KB001" in body
    assert "8" in body
    assert "有库存" in body
    assert "鼠标" in body
    assert "暂无库存" in body


def test_inventory_transactions_show_type_quantity_balance_and_order(app):
    seed_inventory_data(app)
    body = app.test_client().get("/inventory/transactions").get_data(as_text=True)

    assert "入库" in body
    assert "出库" in body
    assert "10" in body
    assert "2" in body
    assert "8" in body
    assert "PO-COMPLETED" in body
    assert "SO-COMPLETED" in body
    assert "变更后库存" in body
