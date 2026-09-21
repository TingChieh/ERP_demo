from flask import Blueprint, redirect, render_template, url_for
from sqlalchemy.exc import SQLAlchemyError

from models import AccountPayable, AccountReceivable, db, utc_now


settlements_bp = Blueprint("settlements", __name__)

RECEIVABLE_STATUS_LABELS = {
    "unpaid": "未收款",
    "paid": "已收款",
}

PAYABLE_STATUS_LABELS = {
    "unpaid": "未付款",
    "paid": "已付款",
}


def _render_receivables(error=None):
    receivables = AccountReceivable.query.order_by(AccountReceivable.id.desc()).all()
    return render_template(
        "receivables/list.html",
        receivables=receivables,
        status_labels=RECEIVABLE_STATUS_LABELS,
        error=error,
    )


def _render_payables(error=None):
    payables = AccountPayable.query.order_by(AccountPayable.id.desc()).all()
    return render_template(
        "payables/list.html",
        payables=payables,
        status_labels=PAYABLE_STATUS_LABELS,
        error=error,
    )


@settlements_bp.get("/receivables")
def list_receivables():
    return _render_receivables()


@settlements_bp.post("/receivables/<int:receivable_id>/receive-payment")
def receive_payment(receivable_id):
    receivable = db.get_or_404(AccountReceivable, receivable_id)
    if receivable.status != "unpaid":
        return _render_receivables(error="该应收账款已收款"), 400

    try:
        # Settlement changes only the financial record. Sales fulfillment and
        # inventory are separate dimensions and must remain untouched here.
        receivable.status = "paid"
        receivable.paid_at = utc_now()
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return _render_receivables(error="收款失败，请稍后重试"), 500

    return redirect(url_for("settlements.list_receivables"))


@settlements_bp.get("/payables")
def list_payables():
    return _render_payables()


@settlements_bp.post("/payables/<int:payable_id>/pay")
def pay_payable(payable_id):
    payable = db.get_or_404(AccountPayable, payable_id)
    if payable.status != "unpaid":
        return _render_payables(error="该应付账款已付款"), 400

    try:
        # Supplier payment settles the liability only. The receipt already
        # completed procurement and created the inventory balance earlier.
        payable.status = "paid"
        payable.paid_at = utc_now()
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return _render_payables(error="付款失败，请稍后重试"), 500

    return redirect(url_for("settlements.list_payables"))
