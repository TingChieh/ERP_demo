import json

from sqlalchemy.exc import SQLAlchemyError

from models import ApiCallLog, DatabaseOperationLog, db


def _serialize_detail(detail):
    if detail is None:
        return "{}"
    return json.dumps(detail, ensure_ascii=False, default=str, sort_keys=True)


def record_database_operation(
    *,
    source,
    action,
    entity_type=None,
    entity_id=None,
    status="success",
    duration_ms=None,
    detail=None,
    error_message=None,
):
    """Persist a best-effort business audit record without masking ERP results."""
    try:
        db.session.add(
            DatabaseOperationLog(
                source=source,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                status=status,
                duration_ms=duration_ms,
                detail_json=_serialize_detail(detail),
                error_message=error_message,
            )
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()


def record_api_call(
    *,
    provider,
    model=None,
    endpoint=None,
    request_id=None,
    status,
    http_status=None,
    duration_ms=None,
    tool_name=None,
    prompt_tokens=None,
    completion_tokens=None,
    total_tokens=None,
    detail=None,
    error_message=None,
):
    """Persist safe outbound-call metadata; never accept secret payloads here."""
    try:
        db.session.add(
            ApiCallLog(
                provider=provider,
                model=model,
                endpoint=endpoint,
                request_id=request_id,
                status=status,
                http_status=http_status,
                duration_ms=duration_ms,
                tool_name=tool_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                detail_json=_serialize_detail(detail),
                error_message=error_message,
            )
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
