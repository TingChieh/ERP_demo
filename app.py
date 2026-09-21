from pathlib import Path
import os

from flask import Flask, render_template
from sqlalchemy import func

from config import load_local_config
from models import (
    AccountPayable,
    AccountReceivable,
    Product,
    PurchaseOrder,
    SalesOrder,
    db,
)
from routes.customers import customers_bp
from routes.assistant import assistant_bp
from routes.products import products_bp
from routes.purchase_orders import purchase_orders_bp
from routes.sales_orders import sales_orders_bp
from routes.settlements import settlements_bp
from routes.suppliers import suppliers_bp
from routes.logs import logs_bp
from services.replenishment import get_low_stock_analyses


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database.db"
load_local_config()


def create_app(test_config=None):
    """Create the Flask application used by the demo."""
    app = Flask(__name__)
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{DATABASE_PATH}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret-change-me"),
        AGENT_LLM_CLIENT=None,
    )

    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    app.register_blueprint(products_bp)
    app.register_blueprint(purchase_orders_bp)
    app.register_blueprint(sales_orders_bp)
    app.register_blueprint(settlements_bp)
    app.register_blueprint(suppliers_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(assistant_bp)
    app.register_blueprint(logs_bp)

    @app.get("/")
    def dashboard():
        """Show read-only summary metrics for the current ERP data."""
        total_stock = (
            db.session.query(func.coalesce(func.sum(Product.stock), 0)).scalar() or 0
        )
        unpaid_receivable = (
            db.session.query(func.coalesce(func.sum(AccountReceivable.amount), 0))
            .filter(AccountReceivable.status == "unpaid")
            .scalar()
            or 0
        )
        unpaid_payable = (
            db.session.query(func.coalesce(func.sum(AccountPayable.amount), 0))
            .filter(AccountPayable.status == "unpaid")
            .scalar()
            or 0
        )
        sales_total = (
            db.session.query(func.coalesce(func.sum(SalesOrder.total_amount), 0))
            .filter(SalesOrder.status == "completed")
            .scalar()
            or 0
        )

        return render_template(
            "dashboard.html",
            low_stock_items=get_low_stock_analyses(limit=5),
            metrics={
                "product_count": Product.query.count(),
                "total_stock": total_stock,
                "pending_purchase_count": PurchaseOrder.query.filter_by(
                    status="pending_receipt"
                ).count(),
                "pending_sales_count": SalesOrder.query.filter_by(
                    status="pending_shipment"
                ).count(),
                "unpaid_receivable": unpaid_receivable,
                "unpaid_payable": unpaid_payable,
                "sales_total": sales_total,
            },
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
