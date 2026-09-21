from app import create_app
from models import Customer, Product, Supplier, db


def initialize_database(app):
    """Create tables and insert the small set of idempotent demo master data."""
    with app.app_context():
        db.create_all()

        products = [
            {
                "name": "机械键盘",
                "sku": "KB001",
                "purchase_price": 80,
                "sale_price": 120,
            },
            {
                "name": "鼠标",
                "sku": "MS001",
                "purchase_price": 40,
                "sale_price": 69,
            },
        ]
        for data in products:
            if Product.query.filter_by(sku=data["sku"]).first() is None:
                db.session.add(Product(stock=0, **data))

        if Supplier.query.filter_by(name="南京键盘供应商").first() is None:
            db.session.add(Supplier(name="南京键盘供应商", phone=""))

        if Customer.query.filter_by(name="大圣科技").first() is None:
            db.session.add(Customer(name="大圣科技", phone=""))

        db.session.commit()


if __name__ == "__main__":
    initialize_database(create_app())
    print("Database initialized: database.db")
