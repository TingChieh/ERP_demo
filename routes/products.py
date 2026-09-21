from decimal import Decimal, InvalidOperation

from flask import Blueprint, redirect, render_template, request, url_for

from models import Product, db


products_bp = Blueprint("products", __name__, url_prefix="/products")


def _product_form_data(product=None):
    if product is None:
        return {"name": "", "sku": "", "purchase_price": "", "sale_price": ""}

    return {
        "name": product.name,
        "sku": product.sku,
        "purchase_price": str(product.purchase_price),
        "sale_price": str(product.sale_price),
    }


def _validate_product_form(form_data, product_id=None):
    errors = []

    if not form_data["name"]:
        errors.append("商品名称不能为空")

    if not form_data["sku"]:
        errors.append("SKU 不能为空")
    else:
        existing = Product.query.filter_by(sku=form_data["sku"]).first()
        if existing is not None and existing.id != product_id:
            errors.append("SKU 已存在")

    prices = {}
    for field, label in (
        ("purchase_price", "默认采购价"),
        ("sale_price", "默认销售价"),
    ):
        raw_value = form_data[field]
        try:
            price = Decimal(raw_value)
        except (InvalidOperation, ValueError):
            errors.append(f"{label}必须是有效数字")
            continue

        if price < 0:
            errors.append(f"{label}不能小于 0")
        else:
            prices[field] = price

    return errors, prices


@products_bp.get("/", strict_slashes=False)
def list_products():
    products = Product.query.order_by(Product.id.desc()).all()
    return render_template("products/list.html", products=products)


@products_bp.route("/new", methods=["GET", "POST"])
def new_product():
    form_data = _product_form_data()
    errors = []

    if request.method == "POST":
        form_data = {
            "name": request.form.get("name", "").strip(),
            "sku": request.form.get("sku", "").strip(),
            "purchase_price": request.form.get("purchase_price", "").strip(),
            "sale_price": request.form.get("sale_price", "").strip(),
        }
        errors, prices = _validate_product_form(form_data)
        if not errors:
            # New master data starts with zero stock. Stock is not a product
            # attribute users edit; it will change only through later
            # inventory receipt/shipment workflows.
            db.session.add(
                Product(
                    name=form_data["name"],
                    sku=form_data["sku"],
                    purchase_price=prices["purchase_price"],
                    sale_price=prices["sale_price"],
                    stock=0,
                )
            )
            db.session.commit()
            return redirect(url_for("products.list_products"))

    return render_template(
        "products/form.html",
        product=None,
        form_data=form_data,
        errors=errors,
    )


@products_bp.route("/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    product = db.get_or_404(Product, product_id)
    form_data = _product_form_data(product)
    errors = []

    if request.method == "POST":
        form_data = {
            "name": request.form.get("name", "").strip(),
            "sku": request.form.get("sku", "").strip(),
            "purchase_price": request.form.get("purchase_price", "").strip(),
            "sale_price": request.form.get("sale_price", "").strip(),
        }
        errors, prices = _validate_product_form(form_data, product.id)
        if not errors:
            product.name = form_data["name"]
            product.sku = form_data["sku"]
            product.purchase_price = prices["purchase_price"]
            product.sale_price = prices["sale_price"]
            # Deliberately do not read request.form["stock"]. Product stock
            # belongs to inventory workflows, not master-data maintenance.
            db.session.commit()
            return redirect(url_for("products.list_products"))

    return render_template(
        "products/form.html",
        product=product,
        form_data=form_data,
        errors=errors,
    )
