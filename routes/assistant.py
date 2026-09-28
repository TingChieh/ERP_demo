import secrets

from flask import Blueprint, current_app, jsonify, render_template, request, session

from agent.schemas import error_response, message_response
from agent.service import AgentService
from agent.tools import confirm_purchase_order, confirm_sales_order
from services.document_analysis import DocumentInputError, extract_document_text


assistant_bp = Blueprint("assistant", __name__, url_prefix="/assistant")
PENDING_CONFIRMATION_KEY = "assistant_pending_confirmation"
LAST_REPLENISHMENT_CONTEXT_KEY = "assistant_last_replenishment_context"


def _agent_service():
    return AgentService(current_app.config.get("AGENT_LLM_CLIENT"))


def _request_data():
    return request.get_json(silent=True) or request.form


@assistant_bp.get("")
def assistant_page():
    return render_template("assistant.html", prompt=request.args.get("prompt", ""))


@assistant_bp.post("/message")
def assistant_message():
    data = _request_data()
    context = session.get(LAST_REPLENISHMENT_CONTEXT_KEY)
    response = _agent_service().handle_message(
        data.get("message", ""), context=context
    )
    if (
        response.type in {"message", "clarification"}
        and isinstance(response.data, dict)
        and response.data.get("analysis_type") == "replenishment"
    ):
        session[LAST_REPLENISHMENT_CONTEXT_KEY] = [
            {
                "product_name": item.get("product_name"),
                "sku": item.get("sku"),
            }
            for item in response.data.get("items", [])
            if isinstance(item, dict) and item.get("product_name")
        ]
    if response.type == "confirmation":
        token = secrets.token_urlsafe(24)
        session[PENDING_CONFIRMATION_KEY] = {
            "token": token,
            "action": response.action,
            "payload": response.payload,
        }
        response.confirmation_token = token
    return jsonify(response.to_dict())


@assistant_bp.post("/document")
def assistant_document():
    uploads = request.files.getlist("document")
    if len(uploads) != 1 or not uploads[0].filename:
        return jsonify(error_response("请先选择 PDF 或 XLSX 文件。").to_dict()), 400

    try:
        uploaded = uploads[0]
        document_text = extract_document_text(uploaded.filename, uploaded.stream)
        response = _agent_service().interpret_document(
            request.form.get("question", ""), document_text
        )
    except DocumentInputError as exc:
        return jsonify(error_response(str(exc)).to_dict()), 400
    except Exception:
        current_app.logger.exception("AI document interpretation request failed")
        return jsonify(error_response("文件解读失败，请稍后重试。").to_dict()), 500
    return jsonify(response.to_dict())


@assistant_bp.errorhandler(413)
def assistant_request_too_large(_error):
    return jsonify(error_response("文件过大，请上传 10 MiB 以内的文件。").to_dict()), 413


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
