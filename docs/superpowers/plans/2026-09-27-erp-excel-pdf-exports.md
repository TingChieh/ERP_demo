# ERP Excel/PDF Exports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add XLSX/PDF downloads to nine ERP business lists and let the AI assistant generate those same exports by natural-language request.

**Architecture:** A shared allowlisted data catalog and renderer will build files in memory. List routes and an AI export tool will call the same `generate_export` function. AI files will be served by short-lived, one-time random download tokens.

**Tech Stack:** Flask 3, SQLAlchemy 2, openpyxl 3.x, ReportLab 4.x, existing DeepSeek-compatible tool calling.

## Global Constraints

- Export products, customers, suppliers, current inventory, inventory transactions, purchase orders, sales orders, receivables, and payables; exclude system logs.
- Do not accept arbitrary models, field lists, or SQL from route parameters or the AI model.
- Page downloads and assistant downloads call the same exporter.
- Do not change database schema or existing order, inventory, or settlement behavior.
- Preserve all pre-existing user modifications; the current checkout contains uncommitted assistant and business-rule work.

---

## File Structure

- `services/exports.py`: fixed dataset definitions, SQLAlchemy queries, XLSX/PDF renderers, result/error types.
- `services/export_artifacts.py`: short-lived in-memory AI download token registry.
- `routes/exports.py`: direct export and token download routes.
- `agent/tools.py`, `agent/prompts.py`, `agent/service.py`: AI tool implementation and allowlist registration.
- Nine business-list templates: direct export links.
- `static/js/assistant.js`: safe assistant download link presentation.
- `app.py`: blueprint registration.
- `requirements.txt`: openpyxl and ReportLab dependencies.
- `README.md`: user-facing export coverage and examples.

## Task 1: Define export datasets and deterministic row queries

**Files:**

- Create: `services/exports.py`

**Interfaces:**

- `ExportRequestError(ValueError)`: raised for unknown dataset or file format.
- `ExportColumn`: immutable dataclass with `label: str`, `kind: str` (`text`, `integer`, or `money`).
- `ExportDataset`: immutable dataclass with `dataset_id: str`, `title: str`, `columns: tuple[ExportColumn, ...]`, and `query_rows: Callable[[], list[tuple[object, ...]]]`.
- `list_export_datasets() -> tuple[str, ...]`: returns IDs in catalog order.
- `get_export_rows(dataset: str) -> tuple[ExportDataset, list[tuple[object, ...]]]`: validates ID and returns the catalog and rows.

- [x] Define `ExportRequestError`, `ExportColumn`, and `ExportDataset` in `services/exports.py`; create a fixed dictionary with IDs `products`, `customers`, `suppliers`, `inventory`, `inventory_transactions`, `purchase_orders`, `sales_orders`, `receivables`, and `payables`.
- [x] Set each dataset's column labels and types. Product export columns are name, SKU, purchase price, sale price, and stock; current inventory is name, SKU, and stock; parties include name and phone; transaction rows include product, SKU, movement label, quantity, related order, resulting balance, and timestamp; order rows include number, party, status label, total, creation time, and a joined item summary; financial rows include party, related order, amount, status label, created time, and settled time.
- [x] Implement each query using only the named SQLAlchemy models in `models.py`. Sort by ID descending except current inventory, sorted by product name then ID. Use `selectinload`/`joinedload` for order items and their products and related party fields.
- [x] Normalize datetimes to a readable local-independent string and amounts to `Decimal` values. Do not convert monetary values to formatted text in the query layer.
- [x] Implement `list_export_datasets()` from the catalog keys and `get_export_rows()` with an explicit unknown-ID error.

**Deliverable check:** Every approved dataset has one stable ID, title, typed column list, and deterministic rows independent of route or AI code.

## Task 2: Render the catalog as XLSX and PDF

**Files:**

- Modify: `services/exports.py`
- Modify: `requirements.txt`

**Interfaces:**

- `ExportFile`: immutable dataclass with `content: bytes`, `filename: str`, and `mime_type: str`.
- `generate_export(dataset: str, file_format: str) -> ExportFile`: accepts only catalog IDs and `xlsx` or `pdf`.

- [x] Add `openpyxl>=3.1,<4` and `reportlab>=4,<5` to `requirements.txt`.
- [x] Implement XLSX rendering using an in-memory `openpyxl.Workbook` and `BytesIO`. Add a title row, styled bold header, frozen header row, autofilter, useful column widths, numeric cells for integer/money columns, and `¥#,##0.00` for money.
- [x] Write every `text` value as a literal string cell; set the cell type to string after assignment so values beginning with `=` cannot become formulas.
- [x] Implement PDF rendering using ReportLab `SimpleDocTemplate` and `Table` in `BytesIO`. Use landscape A4 for tables wider than five columns, repeat the header, wrap content with `Paragraph`, and apply `html.escape` to every cell before layout.
- [x] Register `UnicodeCIDFont("STSong-Light")` once with `pdfmetrics` and use it in PDF styles for the project's Simplified Chinese labels/content.
- [x] Set MIME types to `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` and `application/pdf`; use fixed dataset ID plus date for safe filenames.
- [x] Implement `generate_export()` dispatch and raise `ExportRequestError` for a file format outside `xlsx`/`pdf`. Keep renderer exceptions separate from user input errors.

**Deliverable check:** Each catalog dataset returns a valid in-memory XLSX or PDF file with the same rows and safe Chinese rendering.

## Task 3: Expose direct downloads on each business list

**Files:**

- Create: `routes/exports.py`
- Modify: `app.py`
- Modify: `templates/products/list.html`
- Modify: `templates/customers/list.html`
- Modify: `templates/suppliers/list.html`
- Modify: `templates/inventory/current.html`
- Modify: `templates/inventory/transactions.html`
- Modify: `templates/purchase_orders/list.html`
- Modify: `templates/sales_orders/list.html`
- Modify: `templates/receivables/list.html`
- Modify: `templates/payables/list.html`

**Interfaces:**

- `GET /exports/<dataset>/<file_format>`: generates and returns an attachment.
- `exports_bp = Blueprint("exports", __name__, url_prefix="/exports")`.

- [x] Create the export blueprint route and call only `generate_export()`. Return `send_file(BytesIO(result.content), as_attachment=True, download_name=result.filename, mimetype=result.mime_type)`.
- [x] Map unknown datasets to HTTP 404 and unsupported formats to HTTP 400; return a generic HTTP 500 for unexpected export errors without exposing exception text or paths.
- [x] Register `exports_bp` in `create_app` in `app.py`.
- [x] Add “导出 Excel” and “导出 PDF” links to all nine in-scope list templates using their fixed dataset ID and `file_format`. Keep each page's current filters, table, and actions unchanged.
- [x] Do not add links to logs or duplicate filtered receipt/shipment lists; purchase and sales order exports cover all statuses from their existing order list pages.

**Deliverable check:** Every in-scope list has direct links for both formats and no page can select another dataset through user-controlled row/column parameters.

## Task 4: Store and serve short-lived AI exports

**Files:**

- Create: `services/export_artifacts.py`
- Modify: `routes/exports.py`

**Interfaces:**

- `store_export_artifact(export_file: ExportFile) -> str`: stores a file in `current_app.extensions` under a random token with a 10-minute expiry.
- `consume_export_artifact(token: str) -> ExportFile | None`: removes and returns a live token once.
- `GET /exports/download/<token>`: serves a one-time artifact or returns 404.

- [x] Implement the registry with a `threading.Lock` and `secrets.token_urlsafe(32)` keys; prune expired entries on insert/consume and evict the earliest-expiring item if more than 50 files are stored.
- [x] Add the token route and serve bytes using `send_file`; set `Cache-Control: no-store` and never interpret the token as a path.
- [x] Return 404 for missing, expired, or already-consumed tokens.

**Deliverable check:** AI-generated exports use expiring in-memory data and never create persistent export files.

## Task 5: Register AI export tool and render its download link

**Files:**

- Modify: `agent/tools.py`
- Modify: `agent/prompts.py`
- Modify: `agent/service.py`
- Modify: `static/js/assistant.js`

**Interfaces:**

- `export_dataset(*, dataset: str, file_format: str) -> AgentResponse`: calls `generate_export`, stores the result, and returns `message_response` with `data.download_url` and `data.filename`.
- Add the function to `ALLOWED_TOOLS`; schema enums are generated from `list_export_datasets()` and `("xlsx", "pdf")`.

- [x] Add `export_dataset` to `agent/tools.py`; catch `ExportRequestError` and return a safe clarification/error instead of raising.
- [x] Register the function in `ALLOWED_TOOLS` and add a strict function schema with required `dataset` and `file_format`, exact enums, and `additionalProperties: false`.
- [x] Update the AI system prompt to describe export datasets and ask a clarification if the target or format is ambiguous; do not add arbitrary SQL or model names.
- [x] Let clearly read-only export/download requests reach the export tool even when the dataset name includes status words such as “出库记录” or “付款记录”; keep explicit “确认/执行/立即出库、收款、付款” requests blocked before the LLM call.
- [x] Build the assistant download URL with `url_for("exports.download_assistant_export", token=token)` and include only the URL and safe filename in response data.
- [x] Update `static/js/assistant.js` to render `data.download_url` as an anchor created through DOM APIs. Set `href` and `textContent` separately; never inject returned values into `innerHTML`.
- [x] Preserve the existing order confirmation card and unpaid-receivable detail rendering in the dirty assistant JS file; make additive edits around `addResponse()`.

**Deliverable check:** The AI tool can generate only an approved dataset and output format, and the front end displays its download link without breaking existing assistant responses.

## Task 6: Document export support

**Files:**

- Modify: `README.md`

- [x] Add the nine list export scopes and direct XLSX/PDF actions to the feature list.
- [x] Add sample requests “导出当前库存 Excel” and “把未收应收导出成 PDF” to the AI Assistant section.
- [x] Preserve the existing README edits and append only the export feature notes.

**Deliverable check:** README explains available export scopes, formats, and assistant examples.

## Dependency and API References

- [openpyxl tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html): workbook write/read APIs and `data_only`/read-only behavior.
- [ReportLab fonts](https://docs.reportlab.com/reportlab/userguide/ch3_fonts/): Unicode CID registration and Simplified Chinese `STSong-Light`.
