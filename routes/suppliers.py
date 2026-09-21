from flask import Blueprint, redirect, render_template, request, url_for

from models import Supplier, db


suppliers_bp = Blueprint("suppliers", __name__, url_prefix="/suppliers")


def _supplier_form_data(supplier=None):
    if supplier is None:
        return {"name": "", "phone": ""}
    return {"name": supplier.name, "phone": supplier.phone}


@suppliers_bp.get("/", strict_slashes=False)
def list_suppliers():
    suppliers = Supplier.query.order_by(Supplier.id.desc()).all()
    return render_template("suppliers/list.html", suppliers=suppliers)


@suppliers_bp.route("/new", methods=["GET", "POST"])
def new_supplier():
    form_data = _supplier_form_data()
    errors = []

    if request.method == "POST":
        form_data = {
            "name": request.form.get("name", "").strip(),
            "phone": request.form.get("phone", "").strip(),
        }
        if not form_data["name"]:
            errors.append("供应商名称不能为空")
        else:
            db.session.add(Supplier(**form_data))
            db.session.commit()
            return redirect(url_for("suppliers.list_suppliers"))

    return render_template(
        "suppliers/form.html", supplier=None, form_data=form_data, errors=errors
    )


@suppliers_bp.route("/<int:supplier_id>/edit", methods=["GET", "POST"])
def edit_supplier(supplier_id):
    supplier = db.get_or_404(Supplier, supplier_id)
    form_data = _supplier_form_data(supplier)
    errors = []

    if request.method == "POST":
        form_data = {
            "name": request.form.get("name", "").strip(),
            "phone": request.form.get("phone", "").strip(),
        }
        if not form_data["name"]:
            errors.append("供应商名称不能为空")
        else:
            supplier.name = form_data["name"]
            supplier.phone = form_data["phone"]
            db.session.commit()
            return redirect(url_for("suppliers.list_suppliers"))

    return render_template(
        "suppliers/form.html", supplier=supplier, form_data=form_data, errors=errors
    )
