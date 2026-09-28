# AI PDF/XLSX Interpretation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users upload a searchable PDF or `.xlsx` in the AI assistant and ask for an explanation based on the document contents.

**Architecture:** Parse a bounded document stream in memory into text, then call the existing LLM client with an explicit document-analysis prompt and `tools=[]`. The upload path has no ERP tool dispatch and no persistence; the UI discloses that extracted content is sent to DeepSeek.

**Tech Stack:** Flask 3, openpyxl 3.x, pypdf 5.x/6.x, existing DeepSeek-compatible `AgentService` and `LLMClient`.

## Global Constraints

- Accept PDF with extractable text and `.xlsx`; reject legacy `.xls` and scanned-PDF OCR cases.
- Limit requests to 10 MiB, PDFs to 50 pages, workbooks to 20,000 non-empty cells/100,000 scanned cells, extracted text to 50,000 characters, and expanded XLSX ZIP content to 50 MiB/100 members.
- Parse the uploaded file in memory only; extracted text is sent to configured DeepSeek and is not persisted.
- Treat file contents as untrusted; the interpretation LLM call receives no ERP tools and cannot perform business writes.
- Preserve existing assistant input, confirmation cards, and unpaid-receivable detail behavior in files with user changes.

---

## File Structure

- `services/document_analysis.py`: type/content validation and bounded PDF/XLSX extraction.
- `agent/prompts.py`: isolated document-analysis system prompt.
- `agent/service.py`: safe method that calls the LLM client with an empty tools list.
- `agent/llm.py`: sends `tool_choice="none"` and omits the tools field when the tool list is empty.
- `routes/assistant.py`: multipart upload endpoint and JSON size/error responses.
- `app.py`: global request body limit.
- `templates/assistant.html`, `static/js/assistant.js`, `static/css/style.css`: file picker, privacy disclosure, multipart request, and answer display.
- `requirements.txt`: pypdf dependency; openpyxl must also be declared if the export plan has not yet added it.
- `README.md`: supported file formats, limits, and data-transfer explanation.

## Task 1: Extract bounded document text without persistence

**Files:**

- Create: `services/document_analysis.py`
- Modify: `requirements.txt`

**Interfaces:**

- `DocumentInputError(ValueError)`: contains a safe user-facing error message.
- `extract_document_text(filename: str, stream: BinaryIO) -> str`: returns bounded plain text or raises `DocumentInputError`.
- Constants: `MAX_DOCUMENT_PAGES = 50`, `MAX_WORKBOOK_CELLS = 20_000`, `MAX_WORKBOOK_SCANNED_CELLS = 100_000`, `MAX_EXTRACTED_CHARS = 50_000`, `MAX_XLSX_MEMBERS = 100`, and `MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024`.

- [x] Add `pypdf>=5,<7` to `requirements.txt`; ensure `openpyxl>=3.1,<4` is present for `.xlsx` parsing.
- [x] Normalize the supplied filename with `Path(filename).name`, lowercase its extension, and accept only `.pdf` and `.xlsx`.
- [x] For PDF, verify `%PDF-` magic bytes, construct `pypdf.PdfReader(stream)`, reject encrypted documents and more than 50 pages, and collect `page.extract_text() or ""` with a `PDF 第 N 页` marker per page.
- [x] If all PDF pages contain no extractable text, raise a message explaining that scanned PDFs need OCR and are not supported yet.
- [x] For XLSX, open the stream as a ZIP first; reject an invalid ZIP, more than 100 entries, or aggregate uncompressed member size above 50 MiB before calling openpyxl.
- [x] Load XLSX with `load_workbook(stream, read_only=True, data_only=True, keep_links=False)`. Call `worksheet.reset_dimensions()` before iterating so the parser uses actual XML rows instead of trusting an oversized declared worksheet range; do not evaluate formulas or links.
- [x] Count non-empty cells, scanned cells, and serialized characters during extraction; raise a clear limit error once 20,000 non-empty cells, 100,000 scanned cells, or 50,000 characters would be exceeded. Never silently truncate omitted content.
- [x] Close the workbook in `finally`; never create a local file, database row, session value, or export artifact from the upload.
- [x] Convert parser, ZIP, XML, and I/O exceptions to a generic damaged/invalid-file `DocumentInputError` without exposing internal exception strings.

**Deliverable check:** Supported streams return text with page/sheet boundaries; all invalid, empty, encrypted, and over-limit cases fail with safe messages and no file persistence.

## Task 2: Add no-tools document interpretation to the agent

**Files:**

- Modify: `agent/prompts.py`
- Modify: `agent/service.py`
- Modify: `agent/llm.py`

**Interfaces:**

- `DOCUMENT_ANALYSIS_PROMPT`: Chinese system instruction that answers only from document content, treats it as untrusted input, ignores embedded instructions, states when evidence is absent, and refuses ERP actions.
- `AgentService.interpret_document(question: str, document_text: str) -> AgentResponse`: calls `self.llm_client.parse_message(..., system_prompt=DOCUMENT_ANALYSIS_PROMPT, tools=[])` and accepts only a string response.

- [x] Define `DOCUMENT_ANALYSIS_PROMPT` separately from `SYSTEM_PROMPT`; state that content between document delimiters is data rather than instruction and the model must not claim to read omitted content.
- [x] Compose a single user message containing the user's question and extracted text in a JSON-encoded `document_text` field; do not add a filesystem path or save the filename in application state.
- [x] Call `parse_message` with `tools=[]`. Update `DeepSeekLLMClient.parse_message` so an empty tool list omits the `tools` request field and sets `tool_choice="none"`; when tools exist, preserve the existing `tools` field and `tool_choice="auto"`.
- [x] If the LLM client returns a `ToolCall`, return a safe error response; do not pass it to `ALLOWED_TOOLS`.
- [x] Map `LLMConfigurationError` and `LLMResponseError` through the existing safe response helpers. Do not return exception text or log document content.
- [x] Keep document uploads outside the normal ERP tool dispatch path; preserve existing tools and operation guards except for the separate read-only export intent handling in the companion export task.

**Deliverable check:** A direct call to `interpret_document` can return only a plain-text answer or a safe error and has no ERP tool dispatch path.

## Task 3: Add the multipart assistant endpoint and request-size handling

**Files:**

- Modify: `app.py`
- Modify: `routes/assistant.py`

**Interfaces:**

- `POST /assistant/document`: multipart fields `document` (required) and `question` (optional); returns the existing `AgentResponse.to_dict()` JSON shape.
- `MAX_CONTENT_LENGTH = 10 * 1024 * 1024` default in app config, with normal `test_config` override behavior.

- [x] Set `MAX_CONTENT_LENGTH` to 10 MiB in `create_app` defaults before applying caller-supplied `test_config`.
- [x] Add `/document` to `assistant_bp`; require exactly one `document` file and return HTTP 400 for a missing/empty upload.
- [x] Default a blank question to “请总结并解读这个文件。”; call `extract_document_text`, then `_agent_service().interpret_document(question, extracted_text)`.
- [x] Return `DocumentInputError` as an `error_response` with HTTP 400; catch unexpected exceptions and return generic HTTP 500 JSON without exception details.
- [x] Add a blueprint handler for HTTP 413 that returns a JSON `error_response("文件过大，请上传 10 MiB 以内的文件。")` for uploads.
- [x] Do not place uploaded bytes, extracted text, or filename in Flask session or database.

**Deliverable check:** The API accepts a supported multipart upload and responds in the same JSON structure as normal assistant messages; oversized and malformed requests produce JSON errors.

## Task 4: Add the file picker and connect assistant UI

**Files:**

- Modify: `templates/assistant.html`
- Modify: `static/js/assistant.js`
- Modify: `static/css/style.css`

- [x] Add a single optional file input with `accept=".pdf,.xlsx,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"` in the assistant composer.
- [x] Add visible Chinese disclosure that PDF/XLSX text is sent to DeepSeek for interpretation, the original file is not retained, scanned-PDF OCR is unsupported, and legacy `.xls` is unsupported; the scanned-cell safeguard may reject sparse workbooks with an unusually large used range.
- [x] In the form submit handler, keep the existing `/assistant/message` JSON request when no file is selected. When selected, submit `FormData` containing `document` and `question` to `/assistant/document` without manually setting the multipart content-type header.
- [x] Show the question and sanitized basename in the user bubble; clear the file input after the request completes. Use the existing safe bubble renderer for the model response.
- [x] Handle non-JSON/failed HTTP responses by rendering a concise assistant error rather than leaving the chat waiting.
- [x] Add responsive spacing for the file control and disclosure while preserving all existing assistant IDs, selectors, message handlers, order confirmation buttons, and receivable cards.
- [x] Use DOM creation and `textContent` for the filename and answer; never place upload or model text in `innerHTML`.

**Deliverable check:** The assistant supports both the existing text-only flow and one-file PDF/XLSX questions with a clear data-transfer notice.

## Task 5: Document supported interpretation behavior

**Files:**

- Modify: `README.md`

- [x] Document searchable PDF and `.xlsx` input, the limits in this plan, and that image scans and `.xls` are unsupported.
- [x] Explain that extraction happens in memory and extracted content is sent to configured DeepSeek for the answer; the original file is not retained.
- [x] Preserve existing README edits and insert the new subsection next to the AI Assistant documentation.

**Deliverable check:** The assistant page and README explain the accepted formats, limits, OCR boundary, and DeepSeek transfer.

## Dependency and API References

- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html): `PdfReader`/`extract_text()` and the limitation that pypdf does not perform OCR on images.
- [openpyxl tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html): read-only workbook loading and `data_only` behavior.
