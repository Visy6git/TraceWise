# PeriodicX — PBRER Section 16.3 Table Workbench

A local-first POC for learning a client's Section 16.3 table layout from one or more prior PBRER DOCX files, saving an approved reusable template, exploring new Excel sources, proposing source-to-field mappings, calculating explicitly reviewed case/event metrics, and producing a new DOCX copy that retains the client's original document styling.

**Scope is deliberately narrow: Section 16.3 and its tables only.** The application does not attempt to regenerate the full PBRER narrative or other sections.

## Product workflow

### 1. Template Generator

1. Create/select a tenant workspace and enter a template/run name.
2. Upload one or more `.docx` reference reports together. The **first uploaded DOCX is the base document** whose styles and page content will be used for generated reports. Additional DOCX files are reference examples for learning structural variations.
3. The structure agent finds Section 16.3 and extracts its topic-specific tables, labels, merged-cell/row layout metadata, table indexes/styles, search criteria and field locations.
4. The UI renders generic previews with tokens such as `{{topic_initial_cases}}` and `{{evaluation_narrative}}`; it does not treat old-period numbers or narrative as reusable values.
5. The learning run writes `template.schema.json` and `master.md` into its run workspace. `master.md` describes only commonalities and variations observed in the uploaded Section 16.3 material, and includes operational guardrails.
6. Review fields and `master.md`, save changes, then approve the template. History supports viewing, editing drafts, forking approved templates into new drafts, and soft-deleting templates.

Approved templates are immutable. “Edit as draft” creates a new draft record linked to the same immutable base DOCX; it does not overwrite the approved version.

### 2. Generator

1. Select an approved template and enter a new run name and reporting interval.
2. Upload one or more `.xlsx` or legacy `.xls` workbooks.
3. **Stage 1 — Source exploration:** profile workbooks in parallel, detect sheets/header rows, infer column types and potential roles, and write one Markdown column dictionary per workbook plus `master_summary.md` and `source_profiles.json`.
4. **Stage 2 — Mapper:** propose mappings between the template's table fields and uploaded workbook columns. The UI shows mappings, candidate counts, live topic activity, and row/cell evidence. Mappings can be changed before approval.
5. Select the intended count unit explicitly: distinct case identifiers or matching event rows. The system does not assume patient = case = event.
6. Enter updated Evaluation and Conclusion narratives. These are reviewer-authored inputs; they are not generated from a few column names.
7. Approve mappings and generate. A new DOCX copy is created from the template's base document, updating only detected Section 16.3 table cells. Other report content is retained.

Unresolved metrics, source splits, and narratives are rendered as `[REVIEW REQUIRED: ...]` placeholders rather than carrying old-period numeric results into the new report.

## Quick start — Windows PowerShell

Python 3.11+ is recommended.

```powershell
cd pbrer_table_workbench
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 .

### macOS / Linux

```bash
cd pbrer_table_workbench
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

The SQLite database and uploaded/generated workspaces are stored under `WORKSPACE_ROOT` by default (`./workspace`). They are not included in the source ZIP.

## Optional Amazon Bedrock integration

The POC works without Bedrock using deterministic schema/column-name matching. To enable optional Mapper refinement, edit `.env`:

```dotenv
AWS_REGION=your-bedrock-region
BEDROCK_MODEL_ID=your-enabled-model-id-or-inference-profile-arn
BEDROCK_ENABLED=true
BEDROCK_MAX_TOKENS=6000
BEDROCK_TEMPERATURE=0.1
```

No model identifier is hardcoded. The configured identifier must be the exact model ID or inference-profile ARN available to your AWS account in that region. `boto3` uses its normal credential provider chain (for example, an AWS CLI profile, IAM Identity Center/SSO, or an execution role). Do not put AWS access keys in frontend code or commit them in `.env`.

The local identity needs `bedrock:InvokeModel` permission for the configured model/inference profile. The code uses the Bedrock Runtime **Converse** operation; it does not currently use Converse streaming. Check the model's account/region access and any inference-profile requirements in your AWS environment.

For privacy, the current prompt sends template structural metadata/search-term definitions and workbook column metadata to Bedrock. Workbook row samples and case-level records are not included in the Mapper prompt. The deterministic profiler reads row samples locally to infer types. Review this data flow with your security/privacy team before using sensitive customer data.

## Tests and checks

From the project root:

```bash
python -m py_compile app/*.py app/services/*.py
python -m pytest -q
```

The included tests create synthetic DOCX/XLSX fixtures at runtime. They cover Section 16.3-only extraction, repeated/continuation table structure, column profiling, mapping guardrails, period and initial-case filters, case/event count modes, separate denominator sources, and preservation of original DOCX content/styles during rendering.

## Core design principles

- **Template is a structural contract:** field keys and table locators describe where new data belongs; previous-period values are examples, not defaults.
- **Source files are inputs, not workspaces:** uploaded files are only read. Profiles, schemas, mapping proposals and generated DOCX files are written separately under a run's `work/` directory.
- **Mapping is reviewable:** source file, sheet, column, inferred type, semantic role, rule, count unit and evidence are visible to the reviewer.
- **No silent semantic equivalence:** a patient identifier is not automatically a case identifier; a MedDRA HLT/SMQ is not treated as an exact PT list; a case count is not automatically an event count.
- **Deterministic calculations:** numeric results come from Python/pandas calculations on explicitly mapped columns and rule filters, not from LLM numeric guesses.
- **Human approval:** templates must be approved before Generator use; mappings and count mode must be approved before output generation.
- **No carry-forward of old values:** missing calculations and narratives become review placeholders.

## Important limitations — read before using real customer data

This is an engineering POC, not a validated pharmacovigilance reporting system and not a GxP-compliant product.

1. **Authentication/authorization are not implemented.** Tenant IDs are workspace organization keys, not a security boundary. Anyone with access to the local service can select a tenant. Do not deploy this as a shared or internet-facing multi-tenant service without identity, role-based authorization, tenant-scoped storage/database enforcement, audit identities and security review.
2. **SQLite is local persistence.** Completed templates/runs/history survive normal app restarts, but active background tasks are not resumed after a process restart. Interrupted queued/running records are marked failed on startup.
3. **DOCX table extraction is layout-dependent.** The first uploaded DOCX is used as the output style source. The structure extractor uses Word headings and native tables; unusually complex nested tables, drawings, floating objects, scanned pages, protected documents or tables spanning unusual section boundaries may require manual correction. Only `.docx` is accepted in Template Generator.
4. **Excel support:** Generator accepts `.xlsx` and `.xls`. Legacy `.xls` support depends on `xlrd`. Password-protected, macro-dependent, external-link, malformed, or very large files may need preprocessing. The current mapper profiles ordinary worksheet cells; it does not execute Excel formula chains or refresh external links.
5. **MedDRA logic:** exact PT matching is supported when the template search criteria is an explicit PT list and the reviewer confirms the event column is at PT level. HLT/SMQ criteria are marked for manual/hierarchy-aware review; the application does not ship a MedDRA dictionary or expand SMQs/HLTs. Use the correct MedDRA version and licensed terminology data in a real implementation.
6. **Count units and scope:** the PBRER sample explicitly distinguishes event-level presentation and warns that one ICSR can contain multiple records. The user must choose distinct case identifiers or event rows. Case ID is not necessarily a person/patient ID. Reporting-period, initial/follow-up and source-category filters must be mapped and verified. If the selected fields do not support the template's criteria, the metric is blocked or left for review.
7. **Denominator:** same-sheet denominator is the default candidate; a separate denominator sheet can be mapped for distinct-case calculations. The reviewer must confirm that the chosen denominator population matches the report definition.
8. **Narratives:** Evaluation, Conclusion, seriousness/fatality interpretation and data-source references require reviewer inputs/verification. The POC does not autonomously write clinical/regulatory conclusions.
9. **Source split:** Spontaneous and Report from other studies counts are filled only when source categories can be classified and their counts reconcile to the selected numerator. Otherwise the document receives an explicit review placeholder.
10. **Evidence:** row/cell evidence is sampled/capped in the review payload for UI performance. The calculation still operates on the filtered workbook data; a production audit package should persist complete evidence, source checksums, rule version, code version, reviewer identity and immutable run metadata.
11. **AG-UI:** the UI uses SSE events with AG-UI-style lifecycle event names plus `CUSTOM` activity events for the POC. It is an event-compatible implementation pattern, not a claim of a full, conformance-tested AG-UI SDK implementation.
12. **Agent autonomy:** this version uses bounded specialist stages (parallel DOCX extraction, parallel Excel exploration, Mapper refinement) orchestrated by FastAPI. It does not allow an LLM to execute arbitrary code, modify uploaded files, or control the host OS. That is intentional for this data-mapping POC.

## Project layout

```text
pbrer_table_workbench/
├── app/
│   ├── main.py                 # FastAPI routes, runs, history, approvals, SSE
│   ├── db.py                   # SQLite persistence
│   ├── config.py               # Environment configuration
│   ├── services/
│   │   ├── docx_template.py    # Section 16.3 extraction/template learning
│   │   ├── excel_profile.py    # Workbook exploration + Markdown dictionaries
│   │   ├── mapper.py           # Candidate mappings + deterministic metrics
│   │   ├── docx_render.py      # Styled DOCX copy with Section 16.3 updates
│   │   ├── orchestrator.py     # Bounded multi-agent stages
│   │   └── bedrock.py          # Optional boto3 Converse adapter
│   └── static/
│       ├── index.html
│       ├── styles.css
│       └── app.js
├── tests/
├── docs/
├── workspace/                 # Local uploads, database and outputs (not in ZIP)
├── .env.example
└── requirements.txt
```

## Next production engineering steps

Authentication and tenant authorization; source immutability/checksums; complete evidence lineage and rule versioning; durable job queue and resumable runs; validated DOCX table mapping UI; full regulatory terminology service; dataset-level reconciliation against source-of-truth outputs; report-level QA/diffing; human reviewer signatures and audit trails; robust malware/file validation; object storage and encryption; formal validation and change control.
