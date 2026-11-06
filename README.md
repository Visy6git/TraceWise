# Tracewise · PBRER Section 16.3 Review & Autonomous Agent Harness

Tracewise is an autonomous pharmacovigilance (PV) evidence discovery, calculation-rule engineering, and independent validation platform designed for Periodic Benefit-Risk Evaluation Reports (PBRER).

---

## Architecture Overview (Phase 2)

```
                            ORCHESTRATOR
   State Machine · Task Routing · Bounded Retries · Concurrency · Run Management
                                 │
     ┌───────────────────────────┴───────────────────────────┐
     ▼                                                       ▼
EXPLORER AGENT                                         CLAIMS AGENT
Global dataset profiling, schema discovery,            Extracts atomic claims & figures
relationships & join cardinality                       from Section 16.3 leaf subsections
knowledge_graph.json + .md                             claims.json (1 row per figure)
                                                             │
                                                             ▼
                                                    EVIDENCE DISCOVERY
                                                    Queries complete datasets (SQL)
                                                    retrieves exact row provenance
                                                    evidence.json
                                                             │
                                                             ▼
                                                    RULE ENGINEER AGENT
                                                    Builds declarative MetricRule specs
                                                    & compiles to deterministic SQL
                                                    rule.json + result.json
                                                             │
                                                             ▼
                                                      VALIDATOR AGENT
                                                    Independent check: claim, evidence,
                                                    population, join, & reconciliation
                                                    validation.json (max 3 retries)
                                                             │
                                            ┌────────────────┴────────────────┐
                                            ▼                                 ▼
                                     [PASSED: VALIDATED]           [FAILED: Targeted Retry]
                                                                   (Evidence / Rule / Claims)
```

### 1. Specialized Autonomous Agents
- **Orchestrator**: Coordinates execution lifecycle, manages parallel subsection specialists, bounded 3-attempt retry loop, durable run artifacts, and reviewer guidance routing.
- **Explorer Agent**: One global profiling run across the entire uploaded source dataset. Discovers worksheet schemas, total row counts (without 100-row limits), candidate primary keys, and cross-dataset join relationships (e.g. case-level vs drug-event exports) with join cardinality analysis (1:1, 1:N, N:N). Produces `knowledge_graph.json` and human-readable `knowledge_graph.md`.
- **Claims Agent**: Decomposes Section 16.3 leaf subsections into individual atomic claims (one claim per reported figure or statement, preserving original text, target locator, and unit).
- **Evidence Discovery Agent**: Investigates complete source datasets using registered query tools to locate exact supporting records, table schemas, and Excel row coordinates (`__excel_row__`).
- **Rule Engineer Agent**: Constructs declarative `MetricRule` specifications (source table, entity identifier, aggregation, filters, joins) and compiles them into deterministic queries. Also supports sandboxed Python execution for non-declarative calculations.
- **Validator Agent**: Independently verifies claim extraction integrity, evidence support, population filters, join cardinality, deterministic re-execution, and numerical reconciliation against the target report. Dispatches structured feedback to the diagnosed stage during retries (capped at 3 attempts, marking unresolved claims as `UNRESOLVED` rather than falsely verified).

### 2. Analytical Data Engine
- Backed by an isolated SQLite analytical engine (with optional DuckDB acceleration) per run.
- Indexes all records from uploaded spreadsheets and CSVs without preview caps.
- Tracks exact source row numbers (`__excel_row__`) for complete auditability.

### 3. Bedrock Multi-Turn Converse Tool-Use Loop
- Uses AWS Bedrock Converse API with Anthropic Claude Sonnet.
- Implements a complete multi-turn tool interaction loop (`toolUse` -> Python execution -> `toolResult` -> reasoning).
- Includes deterministic local fallback for offline development and CI test execution.

### 4. Interactive UI & Claim Register
- **Left Panel**: Focused Section 16.3 subsection hierarchy with live status tags.
- **Center Panel**: Target report viewer with live agent activity feed and generated run artifacts tray.
- **Right Panel**: Interactive 3-column Section Claim Register (**Claims | Evidence | Rules & Execution**) displaying status pills, matching records, computed figures, and expandable lineage drawers with reviewer guidance.

---

## Quickstart (Windows)

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-dir app --reload-dir static --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Use the **Load PBRER Sample Bundle** button or upload your target report (DOCX/PDF) and source spreadsheets (XLSX/CSV) to launch the review.

---

## Testing

Run the full pytest suite:

```powershell
.venv\Scripts\python.exe -m pytest -v
```

The test suite covers:
- Complete worksheet profiling beyond 100 rows
- Header discovery with metadata rows
- Relationship discovery and join cardinality analysis (1:1, 1:N, N:N)
- Claim atomization (one claim per figure)
- Evidence retrieval with full dataset coordinates
- Distinct entity counting (cases vs events)
- Validator rejection & reconciliation
- Bounded 3-retry loop ending in `UNRESOLVED`
- Reviewer note targeted retry
- Source immutability & read-only protection
- Multi-turn Bedrock Converse tool loop
- FastAPI endpoints and AG-UI event replay
