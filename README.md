# TraceWise — 3-Stage PBRER Claim & Verification Pipeline

TraceWise is a reviewer-gated 3-stage clinical verification platform for Periodic Benefit-Risk Evaluation Reports (PBRER / Section 16.3) backed by Excel/CSV clinical source extracts.

## Architecture Overview

1. **Upload / Intake**: Upload one target clinical report (`.docx`) and supporting source files (`.xlsx` / `.csv`). All original inputs are stored immutably with SHA-256 verification.
2. **Stage 1 — Claims & Source Exploration (`app/stages/stage_1_claims/`)**:
   - **Phase 1A (Agentic Harness — Per Source File)**: Iterates sequentially over each uploaded source file inside an isolated exploration workspace (`app/harness/`), inspects the first 100 lines/rows, writes Python placeholder/navigation logic (`<slug>_explore.py` listing sheet offsets, columns, data types, and unique column values), executes it, and writes a detailed Markdown report (`<slug>.md`). Once the final file finishes, it synthesizes `stage_1_claims/master_source_summary.md`.
   - **Phase 1B (Strands Agent + `@tool` — Subsection by Subsection)**: Parses Section 16.3 of the target `.docx` subsection-by-subsection with complete narrative paragraphs and un-truncated tables, combines it with `master_source_summary.md`, and invokes a Strands Agent (`strands-agents`) calling `@tool register_claim_group` to register hierarchical claims:
     - `parent_claim` (primary numeric proposition)
     - `children_claims` (list of dependent sub-claims; may be empty `[]`)
     - `search_criteria`
     - `source_document_mapped`
     - `evidence_hint` & `verification_plan`
3. **Stage 2 — Rules Engineering (`app/stages/stage_2_rules/`)**:
   - After human review approves Stage 1, iterates claim-by-claim through the integrated **Agentic Harness** (`app/harness/`), supplying the detailed per-file `.md` summary of the mapped source file(s) alongside the full hierarchical claim details.
   - Generates `plan.md`, `analysis.py`, `tests/test_analysis.py`, executes commands inside the workspace with `SOURCE_INPUT_DIR` mounted read-only, validates SHA-256 immutability, and produces `result.json`.
   - Claims passing verification (parent + children) are marked **`verified`** in SQLite and highlighted green in the UI Claim Register.
4. **Stage 3 — Independent Evaluation (`app/stages/stage_3_evaluation/`)**:
   - Explicitly reserved as a **placeholder** stage in both backend API and React UI.

## Repository Layout

```text
app/
  main.py                              FastAPI app shell + /health + /api/config
  config.py                            Environment & LLM provider config (Bedrock / LM Studio)
  api/                                 Upload, runs, stages, claims, review, artifacts, sources, AG-UI SSE
  control_plane/                       Deterministic state machine, approval gates, ACL, invalidation
  harness/                             Integrated coding-agent harness (Agent, LLMClient, scoped tools, runner)
  prompts/                             stage-specific system prompts (source_explorer, claim_extractor, rule_engineer)
  schemas/                             Pydantic v2 hierarchical claim, run, source knowledge & evaluation models
  services/                            SQLite repository, immutable storage, Bedrock, LM Studio Strands adapter, sandbox, SSE
  stages/
    strands_factory.py                 Strands Agent builder (Bedrock / LM Studio OpenAI tools)
    stage_1_claims/                    Per-file harness explorer + subsection Strands claim extractor
    stage_2_rules/                     Per-claim harness verification + sandbox execution
    stage_3_evaluation/                Explicit Stage 3 placeholder
frontend/
  src/App.tsx                          TraceWise workbench UI
  src/components/                      ArtifactViewerModal, ClaimInspector, SourceDrawer, Modals
  src/lib/                             REST API client & AG-UI SSE subscriber
  src/types/                           Domain & AG-UI contracts
tests/                                 Isolated unit, harness, Strands tool, Stage 1/2/3 & API tests
docs/                                  Architecture, AG-UI, and security specifications
infra/                                 AWS deployment skeletons
```

## Running Locally

### Backend API
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

On Windows, start the API with `.\scripts\dev-api.cmd`. This limits reload watching
to application source files so generated run artifacts and database updates do not
restart the server during a stage. If launching Uvicorn manually, use:

```powershell
uvicorn app.main:app --reload --reload-dir app --port 8000
```

Configure `.env` (see `.env.example`) to use Bedrock via boto3:
- Set `MOCK_RUNS_ENABLED=false`, `LLM_PROVIDER=bedrock`, `BEDROCK_ENABLED=true`, `AWS_REGION`, and `BEDROCK_MODEL_ID`.
- Authenticate boto3 with your AWS profile, environment credentials, or an AWS task role; do not put AWS keys in `.env`.
- Set `MOCK_RUNS_ENABLED=true` to run end-to-end with deterministic local Python execution without calling an external LLM server.

### Frontend UI
```bash
cd frontend
npm install
npm run dev
```

Vite reads root `.env` (`MOCK_RUNS_ENABLED`) automatically via `frontend/vite.config.ts` (`VITE_API_MODE=api` when `MOCK_RUNS_ENABLED=false`).
In API mode, use the left-rail **History** tab to reopen a saved run and continue from its persisted stage.

## Tests & Verification

```bash
pytest -v
cd frontend && npm run typecheck && npm run build
```
