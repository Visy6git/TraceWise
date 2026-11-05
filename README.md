# Tracewise · PBRER Document Intelligence & Agent Autonomy POC

A local-first document intelligence platform for **ICH E2C(R2) Periodic Benefit-Risk Evaluation Reports (PBRER)** and complex regulatory safety reporting.

Tracewise pairs the skeletal outline of a target regulatory report with heterogeneous source evidence (clinical trial exposures, global sales DDD estimations, spontaneous ICSR adverse event line listings, and safety signal logs). Specialized autonomous agents collaborate in an isolated execution sandbox, authoring and executing Python programs to derive verifiable, deterministic data lineage without hallucination.

---

## 🌟 Key Features

1. **Bifurcated Document Ingestion**:
   - **Target Report (DOCX / PDF)**: Extracts and visualizes the hierarchical section outline (e.g., Section 5.1 Clinical Exposure, Section 5.2 Marketing Patient-Years, Section 7.2 Serious ICSR Tabulations, Section 9.1 Safety Signals).
   - **Heterogeneous Sources (XLSX, XLS, CSV)**: Profiles multi-tab Excel files, detects headers, types, row counts, and data schemas while maintaining originals as strictly **READ-ONLY**.

2. **Isolated Agent Autonomy Sandbox**:
   - Agents operate inside a per-run isolated virtual workspace (`runtime/{run_id}/sandbox/`).
   - Agents can create, edit, run, and delete Python programs (`pbrer_sec5_exposure_calc.py`, `pbrer_sec7_icsr_safety_metrics.py`, `pbrer_sec9_signal_evaluator.py`).
   - Guardrails prevent path traversal and forbid modifying or deleting source documents.
   - Captures stdout, stderr, execution duration (ms), exit codes, and output artifacts.

3. **Multi-Agent Orchestration & A2A Communication**:
   - **Lead PV Strategist (Orchestrator)**: Deconstructs target sections into work orders and coordinates specialist agents.
   - **Clinical & Market Exposure Specialist**: Formulates patient-year conversions ($Units \times Dose / DDD / 365$) and clinical enrollment sums.
   - **ICSR & Adverse Event Safety Specialist**: Analyzes MedDRA Preferred Terms (Hypotension, Hyperkalaemia, Renal impairment, Acute pancreatitis) and filters serious spontaneous reports.
   - **Safety Signal Specialist**: Evaluates governance status of closed and ongoing safety signals.
   - **Lineage Auditor**: Formulates exact deterministic rules, Excel cell coordinates (e.g. `A2:K351`), and compiles the complete regulatory audit dossier.

4. **AG-UI Protocol Interactive Streaming Telemetry**:
   - Live stream of agent thoughts, A2A messages, sandboxed code execution, file focus beacons, active filtering criteria, and compilation status via Server-Sent Events (`/api/runs/{run_id}/stream`) with polling resilience (`/api/runs/{run_id}/events`).
   - Dynamic **Agent Focus Beacon** highlights which file, sheet, and columns the agent is actively inspecting or slicing.

5. **Human-in-the-Loop Reviewer Guidance**:
   - Reviewers can add domain notes and constraints to any individual section in the UI (e.g., *"Reconfirm that fatal outcome cases are included"*).
   - Agents immediately ingest the guidance, write a refinement script, re-execute verification in the sandbox, and update the lineage matrix.

6. **AWS Bedrock Claude 3.5 Sonnet Integration**:
   - Powered by Anthropic Claude 3.5 Sonnet on AWS Bedrock via `boto3`.
   - Dual-mode architecture: connects to live AWS Bedrock when credentials are configured; includes an intelligent autonomous verification harness that runs locally with 100% functionality when credentials are in another environment.

7. **One-Click PBRER Demo Bundle**:
   - Instantly generates a realistic ICH E2C(R2) PBRER report for active substance *"Nexipril Sodium"* along with 4 multi-tab source Excel spreadsheets.

---

## 🚀 Quickstart

### 1. Activate Environment & Install Dependencies
```bash
cd document_intelligence_poc
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Run the Local Server
```bash
uvicorn app.main:app --reload --port 8000
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

### 3. Test with One-Click Demo
1. Click **⚡ Load PBRER Sample Bundle** in the top bar.
2. The UI automatically profiles the documents, populates the Target Report Skeletal on the left, and mounts the 4 source Excel files on the right.
3. The multi-agent swarm launches inside the sandbox.
4. Watch the center panel stream live AG-UI thoughts, A2A work orders, generated Python scripts, and sandbox terminal logs.
5. Click any section in the left panel to review mapped sources, cell coordinates, and submit reviewer notes!
6. Click **📋 View Full Lineage Matrix** to export the regulatory audit dossier JSON.

---

## ⚙️ AWS Bedrock Configuration (Claude 3.5 Sonnet)

Set the following environment variables or add them to your `.env` file:

```bash
# Model ID for Claude 3.5 Sonnet v2 on Bedrock (or your region inference profile ARN)
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
BEDROCK_ENABLED=true
AWS_REGION=us-east-1

# Standard AWS credential chain (SSO, profile, or environment variables)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
```

When `BEDROCK_ENABLED=true` and AWS credentials are valid, the adapter in `app/services/bedrock.py` connects via `boto3.client('bedrock-runtime').converse(...)`. If credentials are not present locally, the system runs with the autonomous sandbox verification harness so you can develop, test, and demonstrate seamlessly.

---

## 🧪 Automated Tests

Run the test suite:
```bash
pytest
```
Verifies sandbox lifecycle, security boundaries, multi-agent orchestration, AG-UI event protocol, and deterministic calculation rules.

---

## 🔒 Safety & Governance Architecture

- **Protected Sources**: Uploaded source files are strictly READ-ONLY. The execution harness prevents deletion, path traversal, or modification of any file in `input/`.
- **Per-Run Sandbox**: Agent-generated scripts (`.py`) and data outputs (`.json`) are quarantined inside `runtime/{run_id}/sandbox/`.
- **Zero Hallucination Policy**: Numeric report metrics are derived exclusively through deterministic calculation scripts with verified Excel row and cell coordinate audit trails.
