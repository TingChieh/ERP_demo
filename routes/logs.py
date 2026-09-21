from flask import Blueprint, render_template

from models import ApiCallLog, DatabaseOperationLog


logs_bp = Blueprint("logs", __name__, url_prefix="/logs")


@logs_bp.get("/database")
def database_logs():
    logs = DatabaseOperationLog.query.order_by(DatabaseOperationLog.id.desc()).limit(200).all()
    return render_template("logs/database.html", logs=logs)


@logs_bp.get("/api")
def api_logs():
    logs = ApiCallLog.query.order_by(ApiCallLog.id.desc()).limit(200).all()
    return render_template("logs/api.html", logs=logs)
