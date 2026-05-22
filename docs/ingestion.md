# Ingestion

## Supported input types

Implemented:

- Text JSON with `title` and `content`
- `.txt`
- `.md`
- `.docx`
- `.csv`
- `.xlsx`

Not implemented:

- PDF
- OCR
- image parsing

## Endpoints

- `POST /ingest/text`
- `POST /ingest/files`

## Normalized document model

All ingestion sources are converted into a common internal representation before chunking:

- `title`
- `source_type`
- `content`
- `metadata`
- `url`
- `original_filename`
- `mime_type`
- `created_by`
- `created_at`
- `sections`

## Parser behavior

### TXT

- UTF-8 text is decoded and stored as plain text

### Markdown

- Preserves heading structure in `sections` when headings are present
- Falls back to plain content chunking if needed

### DOCX

- Reads paragraphs with `python-docx`
- Uses paragraph styles containing `heading` to derive sections

### CSV

- Reads rows with Python `csv.DictReader`
- Converts each readable row into retrieval-friendly text
- Includes:
  - row number
  - column headers
  - column values

### XLSX

- Reads workbook sheets with `openpyxl`
- Converts each readable row into retrieval-friendly text
- Includes:
  - workbook filename
  - sheet name
  - row number
  - column headers
  - row values

## Metadata captured

Depending on source type, stored metadata may include:

- `title`
- `created_by`
- `source_kind`
- `source_type`
- `chunk_index`
- `original_filename`
- `mime_type`
- `section_title`
- `sheet_name`
- `row_start`
- `row_end`
- `column_headers`

## Batch behavior

`POST /ingest/files` is partial-success safe:

- one bad file does not fail the entire request
- unsupported file types return per-file errors
- empty files return per-file errors
- remaining files continue processing
- exact duplicate uploads are deduplicated by normalized content hash plus embedding profile, so the same knowledge base is not indexed twice for the same embedding setup

Client payload notes:

- `POST /ingest/text` accepts only `items[].title` and `items[].content`
- `POST /ingest/files` accepts only uploaded files
- source type, file name, MIME type, metadata, `created_by`, and `created_at` are populated by the backend

## Canonical embedding enforcement

The active embedding profile comes from the model-selection record in PostgreSQL and must match one of the configured entries in `backend/app/core/config.py`.

If the profile uses a new embedding dimension, the app creates the matching Qdrant collection automatically on first use.
