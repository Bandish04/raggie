# Document failure codes

When ingestion fails, the ingestion worker stores three fields on the
`documents` row (control-plane migration 0029) and the document list/detail
API returns them:

| Field | Type | Meaning |
|---|---|---|
| `error_code` | string \| null | One of the stable codes below. `null` for rows that failed before codes existed. |
| `error_params` | object \| null | Values for the message (see each code). Keys are stable; values are JSON scalars. |
| `error_message` | string \| null | The same reason as an English sentence. Kept for the API and older clients; the web should render from `error_code` + `error_params` and fall back to `error_message` when the code is `null` or unknown. |

The `raggie.document.failed` event carries `error` (the English sentence) and
`error_code`. Codes are never renamed; new codes may be added, so clients must
handle unknown codes by showing `error_message`.

## Codes

| Code | When | `error_params` | English message (example) |
|---|---|---|---|
| `parse_limit` | A parser resource or size limit was exceeded. | `kind` (below), `limit` (number, when known) | "PDF has more than 1000 pages." |
| `parse_invalid` | The file is corrupt or does not match its declared format. | — | "File does not match its declared office format." |
| `unsupported_format` | The file extension is not supported. | `extension` (e.g. `".zip"`, when known; `"unknown"` unless it matches `[a-z0-9.]{1,16}`) | "Unsupported file type: .zip." |
| `parse_timeout` | Parsing ran past `PARSER_TIMEOUT_SECONDS`; the parser was stopped. | `seconds` | "Document parsing exceeded 120 seconds." |
| `parser_crashed` | The parser process died (usually out of memory). | `exit_code` (number or null) | "Document parser exited unexpectedly (exit code -9)." |
| `fingerprint_mismatch` | The embeddings gateway now uses a different embedding profile than the document's; re-embed required. Not retried automatically. | `expected`, `actual` (8-hex fingerprints) | "Document is indexed with embedding profile 2872ae6a but the gateway now embeds with 5e1f00d2; re-embed required." |
| `embeddings_http` | The embeddings gateway answered with an error status. | `status` (HTTP status) | "The embeddings service answered HTTP 503; embedding failed." |
| `embeddings_unreachable` | The embeddings gateway could not be reached. | — | "The embeddings service could not be reached; embedding failed." |
| `vector_store` | Qdrant rejected or did not answer the upsert. | — | "The vector database did not accept the chunks; indexing failed." |
| `object_read` | The uploaded file could not be read from object storage. | — | "The uploaded file could not be read from object storage." |
| `unexpected` | Anything else. Details are only in the worker log. | — | "Ingestion failed unexpectedly (RuntimeError); details are in the ingestion worker logs." |

### `parse_limit` kinds

| `kind` | Limit (setting) |
|---|---|
| `pdf_pages` | PDF pages (`PARSER_MAX_PDF_PAGES`) |
| `image_pixels` | Image pixels (4 × `PARSER_OCR_MAX_PIXELS`) |
| `extracted_chars` | Extracted text characters (`PARSER_MAX_EXTRACTED_CHARS`) |
| `archive_entries` | Entries in a DOCX/XLSX/PPTX archive |
| `archive_uncompressed_bytes` | Expanded archive size (`PARSER_MAX_ARCHIVE_UNCOMPRESSED_BYTES`) |
| `archive_compression_ratio` | Archive compression ratio (zip-bomb guard) |
| `xlsx_sheets` | Workbook sheets |
| `xlsx_rows` | Rows per sheet |
| `xlsx_columns` | Columns per sheet |
| `xlsx_cells` | Addressable cells (`PARSER_MAX_XLSX_CELLS`) |
| `pptx_slides` | Presentation slides |
| `pptx_shapes` | Presentation shapes (`PARSER_MAX_PPTX_SHAPES`) |
| `complexity` | The document is too complex to parse (memory/recursion); no `limit` |
| `other` | Any other limit; no `limit` |
