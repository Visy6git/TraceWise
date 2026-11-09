# TraceWise — PBRER Evidence Harness

TraceWise has a demo UI and a local live path for DOCX target reports, XLSX/CSV sources, AWS Bedrock claim/rule/evaluation calls, and reviewer-gated stage transitions. It is an engineering prototype, not a validated pharmacovigilance system.

## What is included

- A modern three-panel workbench: document tree + source inventory, report/activity/artifact centre, and claim/agent intelligence panel.
- File intake UI for one target PBRER and multiple sources, with type checks, add/remove, run naming, file inventory and private-input messaging.
- Three visible sequential stages with explicit start/review/approve controls, progress, stage status, agent counts, subagent counts and artifact counts.
- Reviewer gates with approval or change request, manifest/version language, notes and audit-oriented activity entries.
- Claim register with search/status filtering, selected-claim inspector, editable claim draft, evidence hint, observed/inferred/unknown labels, source lineage chips and target-document navigation.
- Report viewer prototype with section highlighting, claim excerpt and table layout.
- Agent view, tool/activity timeline, source inspector drawer and stage-grouped artifact explorer.
- AG-UI event types and SSE client adapter for run activity.
- Typed Pydantic contracts, stage-specific agent packages and prompts, control-plane policy code, tool interfaces, service boundaries, tests and AWS deployment skeletons.

## Run the UI

Requirements: Node.js 20+ and npm.

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL printed by the command (normally `http://localhost:5173`). The UI mode is selected from `MOCK_RUNS_ENABLED` in the repository-root `.env`:

- `true`: demo fixtures and simulated stages; uploads stay in browser memory.
- `false`: live API mode; upload one DOCX report and one or more XLSX/CSV sources, then run each reviewer-gated stage against those files.

Restart the API and Vite servers after changing the flag.

## Run the API

Requirements: Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open `http://localhost:8000/docs` or `http://localhost:8000/health`. The API loads the repository-root `.env` on startup.

For live runs, configure `MOCK_RUNS_ENABLED=false`, `BEDROCK_ENABLED=true`, `AWS_REGION`, and `BEDROCK_MODEL_ID`. AWS credentials must come from the normal AWS credential chain (for example, an AWS profile); do not put keys in `.env`. The configured live profile uses `SANDBOX_BACKEND=local_subprocess` and `SANDBOX_REQUIRED=true`.

**Execution warning:** `local_subprocess` is not an OS/container sandbox. Bedrock-generated Python runs as the API process user and can access that user's files and network despite the prompt restrictions. Use only in a controlled local environment with data and permissions approved for that execution. A proper isolated Docker/ECS sandbox is still required before production use.

Live stages send extracted report blocks, claim details, source schema metadata, generated code, and results to the configured AWS Bedrock account. Use only files authorized for that processing. Stage 3 reruns the same generated code, so a numeric match is not independent validation; such results remain `NEEDS_HUMAN_REVIEW`. Human approvals remain explicit.

## Repository map

```text
app/
  main.py                         FastAPI application shell
  api/                            Upload, run, stage, review and artifact routes
  control_plane/                  State transitions, approval checks, message ACLs, invalidation
  agents/
    base.py                       Strands factory boundary
    claims_orchestrator/          Stage 1 report/source/claim interfaces + prompt
    rules_orchestrator/           Stage 2 coding-agent interfaces + prompt + retry budget
    evaluator_orchestrator/       Stage 3 independent evaluation + prompt
  tools/                          Scoped tool interfaces for agents
  schemas/                        Versioned Pydantic domain/API models
  services/                       DB, storage, extraction, analytics, Bedrock, sandbox, AG-UI
  prompts/                        Shared prompt directory (stage prompts also colocated)
  tests/                          Guardrail and policy tests
frontend/
  src/App.tsx                     Interactive TraceWise workspace
  src/components/                 Reserved component extraction boundary
  src/data/demo.ts                Clearly illustrative local fixture
  src/lib/api.ts                  Typed API client contract
  src/lib/agui.ts                 AG-UI SSE subscription adapter
  src/types/                      Domain and AG-UI event contracts
infra/
  stepfunctions/                  Reviewer-gated state-machine skeleton
  terraform/                      Reserved for infrastructure modules
  ecs/                            Reserved for isolated task definitions
  iam/                            Reserved for role policies
```

## Three-stage workflow

1. **Claims Orchestrator:** read the entire target report and all uploaded sources; build the full outline; identify leaf-level Section 16.3 claims; create one concise, epistemically labelled evidence hint per claim; create `source_knowledge.md`, canonical source JSON and knowledge graph. The Claim Registry is authoritative and editable until reviewer approval.
2. **Rules Orchestrator:** receive only a frozen Stage 1 package; investigate each claim; write a plan, evidence bundle, rule spec, Python, tests, pinned environment, execution logs/results, provenance, tool history and artifact manifest. Repair is bounded. Source originals and approved claims remain read-only.
3. **Evaluator Orchestrator:** start in a fresh context with read-only access; independently inspect and rerun published artifacts in a separate sandbox; classify `PASS`, `DISCREPANCY`, `FAIL`, `INCONCLUSIVE`, `NEEDS_HUMAN_REVIEW` or `UNRESOLVED`; require final human sign-off.

The Run Control Plane is deterministic code outside the LLMs. Claims and Rules do not communicate directly. Cross-stage data moves only through immutable, versioned artifacts and control-plane-routed messages.

## Run the tests

```bash
pytest
```

The tests cover control-plane policies, upload persistence, live/mock separation and fail-closed sandbox behavior. They do not make AWS calls or validate clinical calculations.

Frontend checks:

```bash
cd frontend
npm run typecheck
npm run build
```

## Handoff reading order

1. `docs/IMPLEMENTATION_HANDOFF.md` — detailed work order for the next coding agent.
2. `docs/ARCHITECTURE.md` — ownership, data flow, run state and access boundaries.
3. `docs/AG_UI_CONTRACT.md` — event schema and UI projection contract.
4. `docs/SECURITY_AND_PRIVACY.md` — data, tools, sandbox and AWS safety requirements.
5. `app/agents/*/prompt.md` — stage-specific agent instructions.

## Design sources

- AG-UI 1.0 specification and event schema: https://github.com/ag-ui-protocol/ag-ui/tree/main/docs/spec/1.0
- Strands Agents — Agents as Tools: https://strandsagents.com/docs/user-guide/sdk/multi-agent/agents-as-tools/
- Strands Agents — agent anatomy: https://strandsagents.com/docs/user-guide/sdk/agents/
- TraceWise / Crush-informed engineering blueprint is included in the originating project conversation as `TraceWise_Autonomous_Harness_Implementation_Blueprint.md` and `.docx`.

## Safety warning

The prior repository review identified a public Git repository history containing older PBRER/CSMR runtime workbooks, even though the latest tree excluded those data files. Making the repository private or deleting files from the latest commit does not erase reachable historical Git objects or existing clones. Review/purge history and assess access exposure before using real pharmacovigilance source files. Never place patient-level files, generated workspaces, secrets, runtime artifacts or production logs in Git.
