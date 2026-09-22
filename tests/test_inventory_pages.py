from datetime import datetime, timezone
from html.parser import HTMLParser
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


class TableBodyRowsParser(HTMLParser):
    """Collect text from each data row and cell in a rendered table body."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._inside_tbody = False
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tbody":
            self._inside_tbody = True
        elif self._inside_tbody and tag == "tr":
            self._row = []
        elif self._row is not None and tag == "td":
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "tbody":
            self._inside_tbody = False


def rendered_table_rows(body):
    parser = TableBodyRowsParser()
    parser.feed(body)
    return parser.rows


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
                    created_at=datetime(2026, 9, 22, 0, 1, tzinfo=timezone.utc),
                ),
                InventoryTransaction(
                    product_id=keyboard.id,
                    type="outbound",
                    quantity=2,
                    related_order_no="SO-COMPLETED",
                    balance_after=8,
                    created_at=datetime(2026, 9, 22, 0, 2, tzinfo=timezone.utc),
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


@pytest.mark.parametrize(
    "path,empty_text",
    [
        ("/purchase-receipts", "暂无待入库采购订单"),
        ("/sales-shipments", "暂无待出库销售订单"),
        ("/inventory", "暂无商品库存数据"),
        ("/inventory/transactions", "暂无库存流水记录"),
    ],
)
def test_inventory_pages_apply_toolbar_and_empty_state_hooks(app, path, empty_text):
    body = app.test_client().get(path).get_data(as_text=True)

    assert 'class="inventory-toolbar"' in body
    assert f'inventory-empty">{empty_text}' in body


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

    assert rendered_table_rows(body) == [
        ["机械键盘", "KB001", "8", "有库存"],
        ["鼠标", "MS001", "0", "暂无库存"],
    ]


def test_inventory_transactions_show_type_quantity_balance_and_order(app):
    seed_inventory_data(app)
    body = app.test_client().get("/inventory/transactions").get_data(as_text=True)

    assert rendered_table_rows(body) == [
        [
            "机械键盘",
            "KB001",
            "出库",
            "2",
            "8",
            "SO-COMPLETED",
            "2026-09-22 00:02",
        ],
        [
            "机械键盘",
            "KB001",
            "入库",
            "10",
            "8",
            "PO-COMPLETED",
            "2026-09-22 00:01",
        ],
    ]
