# Architecture and workflow

## System boundary

PeriodicX is a local FastAPI application with a static HTML/CSS/JavaScript client. SQLite stores tenants, template metadata, runs, status and event history. Each run receives a separate workspace:

```text
workspace/<tenant>/template_runs/<run-id>/
  input/   # uploaded reference DOCX; read-only by application convention
  work/    # template.schema.json, master.md

workspace/<tenant>/generator_runs/<run-id>/
  input/   # uploaded Excel workbooks; read-only by application convention
  work/    # per-source .md files, master_summary.md, source_profiles.json,
           # mapping_proposals.json, generated DOCX
```

The POC never intentionally writes to an uploaded input file. Generated artifacts are kept in the corresponding `work/` directory.

## Template schema contract

A template contains:

- tenant, template ID/name, status/version timestamps;
- base DOCX relative path and uploaded reference filenames;
- Section 16.3 table metadata: DOCX table index, topic heading, style, dimensions, row/cell layout, merged-cell notes;
- normalized field entries with stable keys, labels, types, required flags, source intent and Word table cell/paragraph locators;
- search-criteria type and terms (PT/HLT/SMQ/manual);
- whether the table declares initial-case and reporting-interval requirements;
- continuation-table relationships to parent topic tables;
- generic preview tokens, not carry-forward numbers.

The first DOCX upload is the base/style document. Additional DOCX uploads are used as reference examples. Approving a template locks that version. An edit to an approved template is made by forking a draft.

## Generator pipeline

### Stage 1 — exploration

Each workbook is profiled in a worker pool. A profile includes workbook type, sheet name, detected header row, row count, column letters, column names, inferred types, non-empty counts, approximate unique counts, semantic-role hints and local sample values. One Markdown dictionary is generated per workbook. `master_summary.md` consolidates column metadata across the uploaded source set.

### Stage 2 — mapping

The deterministic mapper first proposes a match for roles such as case identifier, event term, source category, initial/follow-up flag and initial approval date. Optional Bedrock refinement receives the template structure and column metadata, not case-level sample rows. Any LLM proposal is validated against actual uploaded column references before it can be shown.

The reviewer may change the source file/sheet/column for each role. The calculation layer rejects mappings that cross unsupported workbook/sheet boundaries for related role groups. When the template requires interval or initial-case filtering, the corresponding columns and values must be mapped explicitly.

### Calculation model

Supported count modes:

- `distinct_case`: count distinct, non-empty values in the mapped case identifier column;
- `event_rows`: count matching event rows.

PT criteria are exact, case-insensitive matches. HLT, SMQ and manual criteria are not expanded into PTs. A separate denominator source can be mapped for distinct-case calculations. Source category splits are emitted only if each category can be classified and the split reconciles to the numerator.

Every candidate retains the selected rule, source references, count unit, reporting interval, initial/follow-up filter and example source row/cell evidence. Ambiguous or incomplete mappings are not converted into numeric outputs.

### Rendering

The renderer opens the approved template's base DOCX and uses the original `docx_table_index` and cell/paragraph locators. It changes text in existing paragraphs rather than rebuilding the document, retaining the table layout and paragraph formatting as far as the underlying Word structure permits. It does not rewrite other sections.

Any uncomputed prior-period count is replaced with a review placeholder. Blank Evaluation/Conclusion fields are also placeholders. The output is a new DOCX file under the Generator run's `work/` directory.

## Live activity protocol

The UI subscribes to Server-Sent Events. The backend emits AG-UI-style lifecycle events (`RUN_STARTED`, `STEP_STARTED`, `STEP_FINISHED`, `RUN_FINISHED`, `RUN_ERROR`) and named `CUSTOM` activity payloads that describe agent, message, file, sheet, number of columns or topic status. The event history is persisted in SQLite for refresh/replay.

## Optional Bedrock

`app/services/bedrock.py` uses `bedrock-runtime.converse()` through boto3. Region and model/inference-profile identifier come from settings. Standard AWS credentials are resolved by boto3. The Mapper can operate without Bedrock.
