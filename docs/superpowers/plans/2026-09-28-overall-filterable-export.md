# ERP 全量与筛选导出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 增加一个网页与 AI 共用的导出能力，可把一个或全部九类 ERP 数据导出为 Excel/PDF，并按创建日期和每数据集条数筛选。

**Architecture:** 在 `services/exports.py` 扩展固定白名单数据集定义，使查询回调接收已经校验的 UTC 时间边界和条数上限；单数据集及多数据集都由同一 XLSX/PDF 渲染流程生成。网页统一导出页通过 POST 调用该服务，AI 的 `export_dataset` 工具传入同样的参数并继续通过短期下载令牌交付文件。

**Tech Stack:** Python、Flask、Flask-SQLAlchemy、SQLite、openpyxl、ReportLab、pytest、Jinja2。

## Global Constraints

- 只导出现有白名单中的商品、客户、供应商、当前库存、库存流水、采购订单、销售订单、应收账款和应付账款。
- 全部 Excel 是一个含九张工作表的 `.xlsx`；全部 PDF 是一个按数据集分节的 PDF。
- 每数据集单独应用最多 10,000 条的上限；留空表示不限制。
- 创建时间筛选使用上海本地包含式日历日期，并映射到 UTC `[start, end)` 查询边界。
- 商品、客户、供应商和当前库存是快照数据集：日期条件不筛选它们，但条数上限仍生效。
- 可筛选数据集按 `created_at DESC, id DESC` 排序；不得通过用户输入动态指定模型、列、表或 SQL。
- 现有列表上的无条件单数据集 Excel/PDF 快捷导出继续完整导出。
- 不修改 schema、业务写入逻辑、订单、库存或财务规则。

---

## 文件结构与职责

- `services/exports.py`：固定数据集注册、日期/条数校验、数据库过滤排序，以及单/多数据集 Excel/PDF 生成。
- `routes/exports.py`：统一导出页 GET、筛选导出 POST、既有快捷下载和 AI 短期下载。
- `templates/exports/index.html`：数据集、格式、开始/结束日期和条数表单，以及快照日期规则提示。
- `templates/base.html`：桌面和移动主导航中的“数据导出”入口。
- `agent/prompts.py`：工具参数 schema 和自然语言导出规则。
- `agent/tools.py`：验证并执行单数据集或全部数据集的筛选导出，再保存短期下载 artifact。
- `tests/test_exports.py`：参数校验、UTC 日期边界、数据查询、排序、上限和文件结构测试。
- `tests/test_exports_routes.py`：统一页、POST 下载、错误响应和快捷路由兼容测试。
- `tests/test_agent_tools.py`：AI 工具参数透传、全部数据集和无效参数测试。
- `tests/test_agent_routes.py`：工具 schema 经 assistant function call 的端到端路由测试。
- `tests/test_ui_layout.py`：新增数据导出页面及导航的共享布局和激活状态测试。
- `README.md`：添加统一导出入口和筛选规则说明。

## Task 1: 日期边界、条数校验与数据库查询

**Files:**
- Modify: `services/exports.py`
- Create: `tests/test_exports.py`

**Interfaces:**
- Produces `ExportFilters(start_at: datetime | None, end_before: datetime | None, limit: int | None)`；`start_at` 和 `end_before` 是按 SQLite UTC-naive 存储约定表示的边界。
- Produces `parse_export_filters(start_date: str | None, end_date: str | None, limit: str | int | None) -> ExportFilters`。
- Changes each `ExportDataset.query_rows` to accept `(filters: ExportFilters) -> list[tuple[object, ...]]` and adds `supports_date_filter: bool`.
- Changes `get_export_rows(dataset: str, filters: ExportFilters | None = None) -> tuple[ExportDataset, list[tuple[object, ...]]]`.

- [x] **Step 1: Add tests for inclusive Shanghai dates and optional boundaries**

In `tests/test_exports.py`, create an app fixture using a temporary SQLite database, then add:

```python
def test_parse_export_filters_converts_inclusive_shanghai_days_to_utc():
    filters = parse_export_filters("2026-09-28", "2026-09-29", "5")

    assert filters.start_at == datetime(2026, 9, 27, 16, 0)
    assert filters.end_before == datetime(2026, 9, 29, 16, 0)
    assert filters.limit == 5


def test_parse_export_filters_keeps_a_single_date_boundary():
    filters = parse_export_filters(None, "2026-09-28", None)

    assert filters.start_at is None
    assert filters.end_before == datetime(2026, 9, 28, 16, 0)
    assert filters.limit is None
```

- [x] **Step 2: Run the focused tests and confirm the new interface is missing**

Run: `python -m pytest tests/test_exports.py -q`
Expected: collection or assertion failure because `parse_export_filters` and `ExportFilters` are not implemented yet.

- [x] **Step 3: Implement the validated filter value and UTC conversion**

In `services/exports.py`, add imports for `date`, `datetime`, `time`, `timedelta`, `timezone`, and `ZoneInfo`, plus:

```python
MAX_EXPORT_ROWS = 10_000
EXPORT_TIME_ZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ExportFilters:
    start_at: datetime | None = None
    end_before: datetime | None = None
    limit: int | None = None
```

Implement `parse_export_filters` to accept blank dates/limit as `None`, require dates to round-trip through `date.fromisoformat(value).isoformat()`, reject a start after the end, reject booleans/non-integers and counts outside `1..MAX_EXPORT_ROWS`, and convert local midnight to UTC with `replace(tzinfo=None)` only after conversion for SQLite comparisons.

Use this implementation shape so form strings and AI integers share the same checks:

```python
def _parse_local_date(label, value):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ExportRequestError(f"{label}格式应为 YYYY-MM-DD。")
    raw = value.strip()
    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        raise ExportRequestError(f"{label}格式应为 YYYY-MM-DD。") from None
    if parsed.isoformat() != raw:
        raise ExportRequestError(f"{label}格式应为 YYYY-MM-DD。")
    return parsed


def _utc_naive_start(day):
    return datetime.combine(day, time.min, tzinfo=EXPORT_TIME_ZONE).astimezone(
        timezone.utc
    ).replace(tzinfo=None)


def parse_export_filters(start_date, end_date, limit):
    start_day = _parse_local_date("开始日期", start_date)
    end_day = _parse_local_date("结束日期", end_date)
    if start_day and end_day and start_day > end_day:
        raise ExportRequestError("开始日期不能晚于结束日期。")
    raw_limit = None if limit is None else str(limit).strip()
    if raw_limit == "":
        raw_limit = None
    if isinstance(limit, bool) or (
        raw_limit is not None
        and (not raw_limit.isascii() or not raw_limit.isdigit())
    ):
        raise ExportRequestError("条数必须是 1 至 10,000 的整数。")
    parsed_limit = int(raw_limit) if raw_limit is not None else None
    if parsed_limit is not None and not 1 <= parsed_limit <= MAX_EXPORT_ROWS:
        raise ExportRequestError("条数必须是 1 至 10,000 的整数。")
    return ExportFilters(
        start_at=_utc_naive_start(start_day) if start_day else None,
        end_before=_utc_naive_start(end_day + timedelta(days=1)) if end_day else None,
        limit=parsed_limit,
    )
```

- [x] **Step 4: Add query-level tests for date range, latest-first limit, and snapshot behavior**

Seed three `SalesOrder` rows with explicit UTC `created_at` values around 2026-09-28 Shanghai time. Assert a one-day filter plus `limit=1` returns the newest eligible order. Seed products with ascending IDs and assert a date filter does not remove them from `products`, while `limit=1` still returns one product.

- [x] **Step 5: Run the query tests and confirm they fail before implementation**

Run: `python -m pytest tests/test_exports.py -q`
Expected: failures because dataset callbacks still take no filters and the rows are not date-filtered or capped.

- [x] **Step 6: Extend dataset callbacks to filter and cap within SQL**

Give every callback the signature `query_rows(filters: ExportFilters)`. For each timestamp dataset, build its existing eager-loaded query, add `.filter(Model.created_at >= filters.start_at)` when `start_at` is present, add `.filter(Model.created_at < filters.end_before)` when `end_before` is present, order by `.order_by(Model.created_at.desc(), Model.id.desc())`, apply `.limit(filters.limit)` when present, then call `.all()`. For products, customers, suppliers and inventory, keep their existing stable ordering, skip date predicates, and apply `.limit(filters.limit)` before `.all()`. Mark exactly the five timestamp datasets with `supports_date_filter=True`.

Use shared query helpers so every timestamp dataset has identical range and tie-breaking semantics:

```python
def _created_at_query(query, model, filters):
    if filters.start_at is not None:
        query = query.filter(model.created_at >= filters.start_at)
    if filters.end_before is not None:
        query = query.filter(model.created_at < filters.end_before)
    return query.order_by(model.created_at.desc(), model.id.desc())


def _apply_limit(query, filters):
    return query.limit(filters.limit) if filters.limit is not None else query
```

For example, `_sales_order_rows(filters)` keeps the current eager loads and ends with `_apply_limit(_created_at_query(query, SalesOrder, filters), filters).all()`. `_product_rows(filters)` keeps `order_by(Product.id.desc())` and ends with `_apply_limit(query, filters).all()`.

- [x] **Step 8: Commit the independently verified service/query change**

Run `git add services/exports.py tests/test_exports.py && git commit -m "feat: add export date and row filters"` after the focused test command passes.

- [x] **Step 7: Run the service tests and confirm all filter behaviors pass**

Run: `python -m pytest tests/test_exports.py -q`
Expected: PASS for date parsing, invalid reversed dates, invalid counts, timestamp filtering, latest-first limits, and snapshots unaffected by dates.

## Task 2: Single and all-dataset XLSX/PDF rendering

**Files:**
- Modify: `services/exports.py`
- Modify: `tests/test_exports.py`

**Interfaces:**
- Produces `ALL_DATASET_ID = "all"` and `export_dataset_options() -> tuple[tuple[str, str, bool], ...]` with `(dataset_id, title, supports_date_filter)` entries.
- Changes `generate_export(dataset: str, file_format: str, *, start_date: str | None = None, end_date: str | None = None, limit: str | int | None = None) -> ExportFile` to support either one whitelisted dataset or `all`.
- Preserves `list_export_datasets() -> tuple[str, ...]` as the nine concrete IDs; `all` is a selection operation, not a tenth data set.

- [x] **Step 1: Add tests that inspect all-workbook sheet names and empty datasets**

Add a test that calls `generate_export("all", "xlsx")`, loads `ExportFile.content` with `openpyxl.load_workbook(BytesIO(...), read_only=True)`, and asserts sheet titles appear in `DATASETS` insertion order and all nine sheets exist. Add a test that an empty dataset workbook contains its title/header and a clear empty-result message.

- [x] **Step 2: Run the workbook tests and confirm the all selector currently fails**

Run: `python -m pytest tests/test_exports.py -q`
Expected: `ExportRequestError` for `all` or missing worksheets.

- [x] **Step 3: Extract one-sheet rendering and add all-dataset workbook generation**

Refactor `_render_xlsx(specification, rows)` into `_write_xlsx_sheet(worksheet, specification, rows)`, which writes one named worksheet into a supplied worksheet. Keep the existing formatting, add a literal text row `没有符合条件的记录` when `rows` is empty, and let `_render_xlsx` create a workbook and call the helper on `workbook.active`. For `dataset == "all"`, use the default active worksheet for the first dataset, call `workbook.create_sheet()` for each remaining dataset, write each sheet, and save once. Keep each worksheet title within Excel's 31-character limit.

The helper boundary should have this concrete shape:

```python
def _write_xlsx_sheet(worksheet, specification, rows):
    worksheet.title = specification.title[:31]
    column_count = len(specification.columns)
    worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=column_count)
    title_cell = worksheet.cell(row=1, column=1, value=specification.title)
    title_cell.font = Font(name="等线", size=15, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor="243B53")
    title_cell.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[1].height = 28
    for index, column in enumerate(specification.columns, start=1):
        cell = worksheet.cell(row=2, column=index, value=column.label)
        cell.font = Font(name="等线", bold=True, color="243B53")
        cell.fill = PatternFill("solid", fgColor="E8EEF5")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        worksheet.column_dimensions[cell.column_letter].width = min(
            max(len(column.label) * 2 + 4, 14), 42
        )
    if not rows:
        worksheet.merge_cells(
            start_row=3, start_column=1,
            end_row=3, end_column=len(specification.columns),
        )
        _literal_text_cell(worksheet, 3, 1, "没有符合条件的记录")
    for row_index, row_values in enumerate(rows, start=3):
        for column_index, (column, value) in enumerate(
            zip(specification.columns, row_values), start=1
        ):
            if column.kind == "text":
                cell = _literal_text_cell(worksheet, row_index, column_index, value)
            else:
                cell = worksheet.cell(row=row_index, column=column_index, value=value)
                if column.kind == "money":
                    cell.number_format = MONEY_FORMAT
                    cell.alignment = Alignment(horizontal="right")
            if column.kind == "text":
                worksheet.column_dimensions[cell.column_letter].width = min(
                    max(worksheet.column_dimensions[cell.column_letter].width,
                        len(str(value or "")) + 3),
                    42,
                )
            if column.kind == "text" and column.label == "商品明细":
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    worksheet.freeze_panes = "A3"
    last_row = max(2, worksheet.max_row)
    last_column = worksheet.cell(row=last_row, column=column_count).coordinate
    worksheet.auto_filter.ref = f"A2:{last_column}"
    return worksheet
```

Move the existing title/header/data loops directly into this function rather than introducing another abstraction; do not change established styles or literal-text handling.

- [x] **Step 4: Add PDF tests for one merged report with dataset section names**

Call `generate_export("all", "pdf")` and assert content starts with `%PDF-`. Extract PDF text with `pypdf.PdfReader(BytesIO(content))` and assert it contains all nine section titles, table headers, a clear empty-result message for an empty dataset, and `当前快照，日期范围不适用` for an unfilterable dataset.

- [x] **Step 5: Run the PDF tests and confirm they fail for the all selector**

Run: `python -m pytest tests/test_exports.py -q`
Expected: failure until the multi-section renderer exists.

- [x] **Step 6: Add a multi-section PDF renderer using the existing ReportLab styles**

Refactor the current PDF construction into one shared section renderer for both single and all-dataset PDFs. Use one landscape report page size if any selected dataset has more than five columns; otherwise use portrait A4. Before each section, render its dataset title, add the snapshot note for datasets with `supports_date_filter=False`, render `没有符合条件的记录` when empty, and use `Table(..., repeatRows=1)` so column headers repeat on page breaks. Thus a single snapshot PDF also carries its snapshot note. Preserve the existing escaping and embedded Chinese font behavior.

Represent each selected result as `(specification, rows)` and append a `PageBreak` between sections. Define `_table_for_dataset(specification, rows, available_width, cell_style, header_style)` by moving the existing table-building block out of `_render_pdf`; define `section_title_style` from `title_style` and a small `note_style` with the registered Chinese font. The rendering loop follows this structure:

```python
story = [Paragraph(escape(report_title), title_style)]
for index, (specification, rows) in enumerate(results):
    if index:
        story.append(PageBreak())
    story.append(Paragraph(escape(specification.title), section_title_style))
    if not specification.supports_date_filter:
        story.append(Paragraph("当前快照，日期范围不适用", note_style))
    if rows:
        story.append(_table_for_dataset(
            specification, rows, available_width, cell_style, header_style
        ))
    else:
        story.append(Paragraph("没有符合条件的记录", cell_style))
document.build(story)
```

- [x] **Step 7: Implement shared argument validation, filenames, and metadata options**

Validate `file_format` before querying. Parse filters once with `parse_export_filters`; for a concrete dataset call `get_export_rows` once; for `all`, iterate `DATASETS` in order and collect each `(specification, rows)` result. Name concrete exports `<dataset_id>_YYYYMMDD.<ext>` and all exports `all_data_YYYYMMDD.<ext>`. Implement `export_dataset_options()` from the ordered dataset specs, including date-filter support for the UI.

Use one shared renderer dispatch rather than separate web/AI paths:

```python
def generate_export(dataset, file_format, *, start_date=None, end_date=None, limit=None):
    if file_format not in {"xlsx", "pdf"}:
        raise ExportRequestError("导出格式仅支持 Excel 或 PDF。")
    filters = parse_export_filters(start_date, end_date, limit)
    if dataset == ALL_DATASET_ID:
        results = [get_export_rows(key, filters) for key in DATASETS]
    else:
        results = [get_export_rows(dataset, filters)]
    if file_format == "xlsx":
        content = _render_all_xlsx(results) if dataset == ALL_DATASET_ID else _render_xlsx(*results[0])
        mime_type = XLSX_MIME_TYPE
        extension = "xlsx"
    else:
        content = _render_all_pdf(results) if dataset == ALL_DATASET_ID else _render_pdf(*results[0])
        mime_type = PDF_MIME_TYPE
        extension = "pdf"
    today = datetime.now().strftime("%Y%m%d")
    filename = f"{'all_data' if dataset == ALL_DATASET_ID else dataset}_{today}.{extension}"
    return ExportFile(content=content, filename=filename, mime_type=mime_type)
```

`get_export_rows` must reject an unknown concrete ID before calling a query callback. `_render_all_xlsx(results)` writes one sheet per result; `_render_pdf(specification, rows)` and `_render_all_pdf(results)` both delegate to `_render_pdf_sections(results, report_title)`, which writes one section for a single dataset and one section per result for `all`.

- [x] **Step 8: Run all exporter tests and confirm both formats and filters pass**

Run: `python -m pytest tests/test_exports.py -q`
Expected: PASS for single/all Excel/PDF, order, dates, row limits, snapshots, empty datasets, MIME type, and filenames.

- [x] **Step 9: Commit the independently verified rendering change**

Run `git add services/exports.py tests/test_exports.py && git commit -m "feat: export all ERP datasets to xlsx and pdf"` after the focused exporter tests pass.

## Task 3: Unified export page and validated download route

**Files:**
- Modify: `routes/exports.py`
- Create: `templates/exports/index.html`
- Modify: `templates/base.html`
- Create: `tests/test_exports_routes.py`
- Modify: `tests/test_ui_layout.py`

**Interfaces:**
- `GET /exports/` renders the unified form.
- `POST /exports/` reads `dataset`, `file_format`, `start_date`, `end_date`, and `limit`, calls `generate_export`, and returns the attachment.
- Existing `GET /exports/<dataset>/<file_format>` remains an unfiltered full export for one concrete dataset.

- [x] **Step 1: Add route tests for form rendering, valid POST download, and retained shortcut behavior**

In `tests/test_exports_routes.py`, use the existing temporary-database app fixture pattern. Assert `GET /exports/` displays all dataset options and the snapshot warning. POST `dataset=all`, `file_format=xlsx`, `start_date=2026-09-28`, and `limit=25`; assert status 200, XLSX MIME type, and attachment disposition. Assert `GET /exports/products/xlsx` still returns a full export.

- [x] **Step 2: Run route tests and confirm the unified page does not yet exist**

Run: `python -m pytest tests/test_exports_routes.py -q`
Expected: 404 for `GET /exports/` and missing form/download behavior.

- [x] **Step 3: Add the GET page and POST download endpoints**

In `routes/exports.py`, import `request`, `render_template`, and `export_dataset_options`. Add GET `/` rendering `templates/exports/index.html`. Add POST `/` that calls `generate_export` with the five posted values; on `ExportRequestError`, re-render the form with the message and status 400; on unexpected errors, log the exception and render a generic retry message with status 500. Return valid files through `send_file(BytesIO(...), as_attachment=True, download_name=..., mimetype=...)`. Keep both existing download endpoints intact.

The route shape is:

```python
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
    values = {name: request.form.get(name, "") for name in (
        "dataset", "file_format", "start_date", "end_date", "limit"
    )}
    try:
        export_file = generate_export(
            values["dataset"], values["file_format"],
            start_date=values["start_date"], end_date=values["end_date"],
            limit=values["limit"],
        )
    except ExportRequestError as error:
        return render_template(
            "exports/index.html", datasets=export_dataset_options(),
            error=str(error), form_values=values,
        ), 400
    except Exception:
        current_app.logger.exception("Combined ERP export generation failed")
        return render_template(
            "exports/index.html", datasets=export_dataset_options(),
            error="导出失败，请稍后重试。", form_values=values,
        ), 500
    return send_file(BytesIO(export_file.content), as_attachment=True,
                     download_name=export_file.filename, mimetype=export_file.mime_type)
```

- [x] **Step 4: Add the form template and both navigation links**

Create `templates/exports/index.html` extending `base.html`; include a `method="post"` form, a data set select with `all` followed by the nine options, `.xlsx`/PDF format choices, native `date` inputs, a numeric count input with `min="1" max="10000" step="1"`, an empty-means-unlimited note, the four snapshot datasets named explicitly, and an accessible error region. Add a desktop and mobile “数据导出” navigation link to `url_for('exports.export_page')`, with active state keyed to `exports.export_page` or `exports.create_export`.

The template form must submit these exact names so route and AI arguments line up:

```html
<form method="post" action="{{ url_for('exports.create_export') }}">
  <select name="dataset" required>
    <option value="all">全部数据</option>
    {% for dataset_id, title, supports_date_filter in datasets %}
    <option value="{{ dataset_id }}" {% if form_values.get('dataset') == dataset_id %}selected{% endif %}>{{ title }}</option>
    {% endfor %}
  </select>
  <select name="file_format" required>
    <option value="xlsx" {% if form_values.get('file_format', 'xlsx') == 'xlsx' %}selected{% endif %}>Excel (.xlsx)</option>
    <option value="pdf" {% if form_values.get('file_format') == 'pdf' %}selected{% endif %}>PDF</option>
  </select>
  <input name="start_date" type="date" value="{{ form_values.get('start_date', '') }}">
  <input name="end_date" type="date" value="{{ form_values.get('end_date', '') }}">
  <input name="limit" type="number" min="1" max="10000" step="1" value="{{ form_values.get('limit', '') }}">
  <button type="submit">生成并下载</button>
</form>
```

Use the current `surface-card`, `form-control`, and Bootstrap button classes around these controls; show validation text in `<p role="alert">`.

- [x] **Step 5: Add page and active-navigation layout assertions**

Add `("/exports/", "exports.export_page")` to shared-shell page coverage in `tests/test_ui_layout.py`; assert both desktop/mobile links point to `/exports/` and the selected export page marks exactly its two responsive nav links active.

- [x] **Step 6: Add invalid request tests and confirm the form remains usable**

POST a reversed date range and a count of `10001`; assert status 400, an understandable validation message, and that the response contains the `method="post"` export form. POST an unknown dataset and unknown format and assert they are rejected without creating an attachment.

- [x] **Step 7: Run focused route and layout tests**

Run: `python -m pytest tests/test_exports_routes.py tests/test_ui_layout.py -q`
Expected: PASS, while existing direct list shortcuts continue returning full datasets.

- [x] **Step 8: Commit the independently verified page and route change**

Run `git add routes/exports.py templates/exports/index.html templates/base.html tests/test_exports_routes.py tests/test_ui_layout.py && git commit -m "feat: add unified export page"` after the focused tests pass.

## Task 4: Extend the AI assistant export tool

**Files:**
- Modify: `agent/prompts.py`
- Modify: `agent/tools.py`
- Modify: `tests/test_agent_tools.py`
- Modify: `tests/test_agent_routes.py`

**Interfaces:**
- `export_dataset(*, dataset: str, file_format: str, start_date: str | None = None, end_date: str | None = None, limit: int | None = None) -> AgentResponse`.
- AI schema enum is the nine concrete dataset IDs plus `all`; the date and limit keys are required in strict schema but permit `null`.

- [x] **Step 1: Add direct AI-tool tests for filtered all-export and invalid conditions**

In `tests/test_agent_tools.py`, call `export_dataset(dataset="all", file_format="xlsx", start_date="2026-09-28", end_date=None, limit=3)` inside the app context; assert the response includes a short-lived download URL and a filename beginning `all_data_`. Call it with reversed dates and assert a clarification response without a download URL.

- [x] **Step 2: Run the tool tests and confirm the current signature/schema rejects new parameters**

Run: `python -m pytest tests/test_agent_tools.py -q`
Expected: a `TypeError` or failed assertion because the tool only accepts dataset and format.

- [x] **Step 3: Add nullable filter parameters to the strict function schema**

In `agent/prompts.py`, change the export tool description to mention one or all data sets and date/count filters. Define `dataset` as `enum=list(list_export_datasets()) + ["all"]`, `file_format` as the existing `xlsx`/`pdf` enum, `start_date` and `end_date` as `{"type": ["string", "null"]}`, and `limit` as `{"type": ["integer", "null"], "minimum": 1, "maximum": 10000}`; mark all five keys required to retain strict-schema behavior. Update `SYSTEM_PROMPT` rule 10 to allow optional date range and per-data-set count, describe that omitted count is unlimited and snapshot data ignores dates, and ask for clarification when the requested dataset or format is ambiguous.

The schema property mapping is:

```python
{
    "dataset": {"type": "string", "enum": list(list_export_datasets()) + ["all"]},
    "file_format": {"type": "string", "enum": ["xlsx", "pdf"]},
    "start_date": {"type": ["string", "null"]},
    "end_date": {"type": ["string", "null"]},
    "limit": {"type": ["integer", "null"], "minimum": 1, "maximum": 10000},
}
```

- [x] **Step 4: Pass AI tool filters through the shared service and return clear validation guidance**

Update `agent/tools.py` to accept the five exact keyword-only parameters and call `generate_export(dataset, file_format, start_date=start_date, end_date=end_date, limit=limit)`. Catch `ExportRequestError` and return a clarification response that lists all supported datasets including “全部数据” and explains invalid dates/counts; store valid `ExportFile` objects using the existing `store_export_artifact` and return its existing download URL format.

Retain the current successful response shape; only add function parameters and pass them to the shared service:

```python
def export_dataset(*, dataset, file_format, start_date=None, end_date=None, limit=None):
    try:
        export_file = generate_export(
            dataset, file_format, start_date=start_date,
            end_date=end_date, limit=limit,
        )
    except ExportRequestError as error:
        return clarification_response(f"导出条件无效：{error}")
    token = store_export_artifact(export_file)
    return message_response(
        f"已生成{export_file.filename}，请使用下方链接下载。",
        data={
            "download_url": url_for("exports.download_assistant_export", token=token),
            "filename": export_file.filename,
        },
    )
```

- [x] **Step 5: Add assistant-route tests that inspect schema arguments and download artifacts**

In `tests/test_agent_routes.py`, configure `MockLLMClient` with `ToolCall(name="export_dataset", arguments={"dataset": "all", "file_format": "xlsx", "start_date": None, "end_date": None, "limit": 2})`; POST an export request to `/assistant/message`; assert response type `message`, filename begins `all_data_`, the returned same-origin path starts `/exports/download/`, and GET on that path downloads XLSX bytes.

- [x] **Step 6: Run AI export tests and preserve existing assistant behavior**

Run: `python -m pytest tests/test_agent_tools.py tests/test_agent_routes.py -q`
Expected: PASS for filtered tool arguments, all-dataset downloads, invalid filter clarification, and existing AI read/write confirmation behavior.

- [x] **Step 7: Commit the independently verified AI integration**

Run `git add agent/prompts.py agent/tools.py tests/test_agent_tools.py tests/test_agent_routes.py && git commit -m "feat: add filtered AI export requests"` after the focused tests pass.

## Task 5: Document behavior and verify the complete feature

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-09-28-overall-filterable-export.md`

- [x] **Step 1: Document the page, all-data formats, date semantics, count limit, and snapshot exception**

In `README.md`, add `/exports/` to the page list and update the export capability paragraph to state that one or all supported datasets can be exported to a multi-sheet Excel or consolidated PDF, with optional inclusive Asia/Shanghai creation-date bounds and a per-dataset limit of 1–10,000; a blank limit means unlimited and master/current-inventory snapshots are not date-filtered.

- [x] **Step 2: Run all tests using the repository-supported invocation**

Run: `python -m pytest -q`
Expected: every project test passes without network or a DeepSeek API key.

- [x] **Step 3: Verify the Flask app imports and the export page is registered**

Run: `flask --app app routes`
Expected: route output includes `exports.export_page`, `exports.create_export`, the existing direct export route, and the AI token download route; command exits successfully, confirming the installed XLSX/PDF imports load.

- [x] **Step 4: Check the final diff and commit the feature**

Run `git diff --check`, inspect `git status --short` and `git diff --stat`, then commit the implementation and plan with:

```bash
git add README.md agent/prompts.py agent/tools.py routes/exports.py services/exports.py templates/base.html templates/exports/index.html tests/test_agent_routes.py tests/test_agent_tools.py tests/test_exports.py tests/test_exports_routes.py tests/test_ui_layout.py docs/superpowers/plans/2026-09-28-overall-filterable-export.md
git commit -m "feat: add filtered all-data exports"
```

Expected: clean whitespace check, only intended files changed, and a new commit on `main`.

## Self-Review

- The service task implements concrete and `all` datasets, date/count validation, correct UTC bounds, latest-first stable ordering, snapshots, empty output, and both file formats.
- The web task provides an accessible central page, clear snapshot semantics, server-side validation, and preserves existing list shortcuts.
- The AI task adds the same five schema/tool arguments and uses the shared service plus current short-lived downloads.
- Automated tests cover service boundaries, both renderers, web routes, validation, AI function calls, downloads, and responsive navigation; final verification runs the entire suite and Flask route import.
- No schema, business write, persistence, or export allowlist changes outside the approved nine datasets are planned.
