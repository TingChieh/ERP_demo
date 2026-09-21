from flask import Blueprint, redirect, render_template, request, url_for

from models import Customer, db


customers_bp = Blueprint("customers", __name__, url_prefix="/customers")


def _customer_form_data(customer=None):
    if customer is None:
        return {"name": "", "phone": ""}
    return {"name": customer.name, "phone": customer.phone}


@customers_bp.get("/", strict_slashes=False)
def list_customers():
    customers = Customer.query.order_by(Customer.id.desc()).all()
    return render_template("customers/list.html", customers=customers)


@customers_bp.route("/new", methods=["GET", "POST"])
def new_customer():
    form_data = _customer_form_data()
    errors = []

    if request.method == "POST":
        form_data = {
            "name": request.form.get("name", "").strip(),
            "phone": request.form.get("phone", "").strip(),
        }
        if not form_data["name"]:
            errors.append("客户名称不能为空")
        else:
            db.session.add(Customer(**form_data))
            db.session.commit()
            return redirect(url_for("customers.list_customers"))

    return render_template(
        "customers/form.html", customer=None, form_data=form_data, errors=errors
    )


@customers_bp.route("/<int:customer_id>/edit", methods=["GET", "POST"])
def edit_customer(customer_id):
    customer = db.get_or_404(Customer, customer_id)
    form_data = _customer_form_data(customer)
    errors = []

    if request.method == "POST":
        form_data = {
            "name": request.form.get("name", "").strip(),
            "phone": request.form.get("phone", "").strip(),
        }
        if not form_data["name"]:
            errors.append("客户名称不能为空")
        else:
            customer.name = form_data["name"]
            customer.phone = form_data["phone"]
            db.session.commit()
            return redirect(url_for("customers.list_customers"))

    return render_template(
        "customers/form.html", customer=customer, form_data=form_data, errors=errors
    )
