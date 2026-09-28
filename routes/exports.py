from io import BytesIO

from flask import Blueprint, abort, current_app, render_template, request, send_file

from services.export_artifacts import consume_export_artifact
from services.exports import (
    ExportRequestError,
    export_dataset_options,
    generate_export,
    list_export_datasets,
)


exports_bp = Blueprint("exports", __name__, url_prefix="/exports")


@exports_bp.get("/")
def export_page():
    return render_template(
        "exports/index.html",
        datasets=export_dataset_options(),
        error=None,
        form_values={},
    )


@exports_bp.post("/")
def create_export():
    form_values = request.form.to_dict()
    try:
        export_file = generate_export(
            form_values.get("dataset", ""),
            form_values.get("file_format", ""),
            start_date=form_values.get("start_date"),
            end_date=form_values.get("end_date"),
            limit=form_values.get("limit"),
        )
    except ExportRequestError as error:
        return render_template(
            "exports/index.html",
            datasets=export_dataset_options(),
            error=str(error),
            form_values=form_values,
        ), 400
    except Exception:
        current_app.logger.exception("Combined ERP export generation failed")
        return render_template(
            "exports/index.html",
            datasets=export_dataset_options(),
            error="导出失败，请稍后重试。",
            form_values=form_values,
        ), 500

    return send_file(
        BytesIO(export_file.content),
        as_attachment=True,
        download_name=export_file.filename,
        mimetype=export_file.mime_type,
    )


@exports_bp.get("/<dataset>/<file_format>")
def download_export(dataset, file_format):
    if dataset not in list_export_datasets():
        abort(404)
    if file_format not in {"xlsx", "pdf"}:
        abort(400, "导出格式仅支持 Excel 或 PDF。")

    try:
        export_file = generate_export(dataset, file_format)
    except ExportRequestError:
        abort(400, "导出请求无效。")
    except Exception:
        current_app.logger.exception(
            "ERP export generation failed for dataset %s", dataset
        )
        abort(500, "导出失败，请稍后重试。")

    return send_file(
        BytesIO(export_file.content),
        as_attachment=True,
        download_name=export_file.filename,
        mimetype=export_file.mime_type,
    )


@exports_bp.get("/download/<token>")
def download_assistant_export(token):
    export_file = consume_export_artifact(token)
    if export_file is None:
        abort(404)
    response = send_file(
        BytesIO(export_file.content),
        as_attachment=True,
        download_name=export_file.filename,
        mimetype=export_file.mime_type,
    )
    response.headers["Cache-Control"] = "no-store"
    return response
