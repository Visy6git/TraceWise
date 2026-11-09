# TraceWise — Autonomous PBRER Evidence Harness Starter

A UI-complete, backend-placeholder starter for the three-stage TraceWise architecture in the implementation blueprint.

> **Important:** This is a scaffold, not a functioning pharmacovigilance calculation system. The frontend is interactive and runs with illustrative demo data. Uploads, agent execution, durable persistence, source extraction, calculations, sandboxing, approvals and evaluation are deliberately not connected. Backend endpoints return explicit `501 STARTER_BACKEND_NOT_IMPLEMENTED` responses instead of implying that work took place.

## What is included

- A modern three-panel workbench: document tree + source inventory, report/activity/artifact centre, and claim/agent intelligence panel.
- File intake UI for one target PBRER and multiple sources, with type checks, add/remove, run naming, file inventory and private-input messaging.
- Three visible sequential stages with explicit start/review/approve controls, progress, stage status, agent counts, subagent counts and artifact counts.
- Reviewer gates with approval or change request, manifest/version language, notes and audit-oriented activity entries.
- Claim register with search/status filtering, selected-claim inspector, editable claim draft, evidence hint, observed/inferred/unknown labels, source lineage chips and target-document navigation.
- Report viewer prototype with section highlighting, claim excerpt and table layout.
- Agent view, tool/activity timeline, source inspector drawer and stage-grouped artifact explorer.
- AG-UI event types and SSE client adapter; backend SSE placeholder emits an AG-UI `RUN_STARTED` plus a TraceWise `CUSTOM` event.
- Typed Pydantic contracts, stage-specific agent packages and prompts, control-plane policy code, tool interfaces, service boundaries, tests and AWS deployment skeletons.

## Run the UI

Requirements: Node.js 20+ and npm.

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL printed by the command (normally `http://localhost:5173`). The UI starts in **demo mode** with illustrative data. You can explore the workflow, edit a demo claim, inspect sources, add files to a new local demo run, and simulate each reviewer-gated stage.

The demo upload flow stores file metadata in browser memory only. It does **not** upload file bytes or parse documents.

## Run the API shell

Requirements: Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Then open `http://localhost:8000/docs` or `http://localhost:8000/health`.

The API shell exposes the intended routes and schemas, but the main application operations are placeholders and return HTTP 501. The events endpoint is only a keep-alive SSE demonstration. No real agent starts and no files are persisted. The local `SANDBOX_REQUIRED=true` policy is deliberately fail-closed.

## Repository map

```text
app/
  main.py                         FastAPI application shell
  api/                            Typed HTTP route contracts (explicit 501 stubs)
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

The included tests exercise stage transition guards, stale approval protection, cross-stage message restrictions, dependency invalidation, safe workspace path handling and fail-closed sandbox behavior. They do not test agent execution because no agent execution is connected yet.

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
