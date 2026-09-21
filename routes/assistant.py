import secrets

from flask import Blueprint, current_app, jsonify, render_template, request, session

from agent.schemas import error_response, message_response
from agent.service import AgentService
from agent.tools import confirm_purchase_order, confirm_sales_order


assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")
PENDING_CONFIRMATION_KEY = "assistant_pending_confirmation"


def _agent_service():
    return AgentService(current_app.config.get("AGENT_LLM_CLIENT"))


def _request_data():
    return request.get_json(silent=True) or request.form


@assistant_bp.get("")
def assistant_page():
    return render_template("assistant.html")


@assistant_bp.post("/message")
def assistant_message():
    data = _request_data()
    response = _agent_service().handle_message(data.get("message", ""))
    if response.type == "confirmation":
        token = secrets.token_urlsafe(24)
        session[PENDING_CONFIRMATION_KEY] = {
            "token": token,
            "action": response.action,
            "payload": response.payload,
        }
        response.confirmation_token = token
    return jsonify(response.to_dict())


@assistant_bp.post("/confirm")
def assistant_confirm():
    data = _request_data()
    pending = session.get(PENDING_CONFIRMATION_KEY)
    token = data.get("confirmation_token", "")
    action = data.get("action", "")

    if not pending or not secrets.compare_digest(str(pending["token"]), str(token)):
        return jsonify(error_response("确认已失效或无效，请重新生成订单预览。").to_dict()), 400

    if action == "cancel":
        session.pop(PENDING_CONFIRMATION_KEY, None)
        return jsonify(message_response("已取消本次订单创建。").to_dict())

    if action != "confirm":
        return jsonify(error_response("确认操作无效，未创建订单。").to_dict()), 400

    if pending["action"] == "create_purchase_order":
        response = confirm_purchase_order(pending["payload"])
    elif pending["action"] == "create_sales_order":
        response = confirm_sales_order(pending["payload"])
    else:
        return jsonify(error_response("待确认操作不受支持，未创建订单。").to_dict()), 400

    if response.type == "message":
        session.pop(PENDING_CONFIRMATION_KEY, None)
        return jsonify(response.to_dict())
    return jsonify(response.to_dict()), 400
