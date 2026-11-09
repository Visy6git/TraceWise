# TraceWise: Autonomous Agent Harness for PBRER Section 16.3

**Implementation blueprint and master engineering brief**  
**Repository reviewed:** `Visy6git/TraceWise`, `main` at `15ebf04cc0ccd41b7b828b5e25444ded6eaf1cc8` (6 November 2026)  
**Harness reference:** `charmbracelet/crush`, `main` at `8f1f02951cabc30b82e497fd916ca434bad1e6f4` (7 November 2026)  
**Prepared:** 9 November 2026  
**Scope:** Replace the current agent execution approach with a three-stage, reviewer-gated, tool-using agent harness on AWS Bedrock and Strands Agents.

---

## 1. Executive decision

TraceWise should be rebuilt around **three sequential, independently scoped agent orchestrators**, controlled by a durable application-level run coordinator:

1. **Claims Orchestrator — Stage 1:** Understand the complete target report and every uploaded source; identify the full section hierarchy; extract atomic claims only at the lowest-level Section 16.3 subsections; create one concise evidence hint per claim; and maintain an editable, versioned Claim Register. It also creates a human-readable `source_knowledge.md` and a structured source knowledge graph.
2. **Rules Orchestrator — Stage 2:** Take the reviewer-approved, immutable Stage 1 package and autonomously investigate each claim. It behaves like a coding agent: plan, inspect, search, write, edit, execute, test, inspect failures, revise, and produce reproducible Python and evidence artifacts. It may launch scoped specialist subagents.
3. **Evaluator Orchestrator — Stage 3:** Start in a fresh context and independently examine the approved claims and Stage 2 artifacts. It verifies that the code, actual source records, filters, entity definitions, results, and lineage support each claim. It must not trust the Rules Orchestrator's success status or simply repeat its reasoning.

A non-LLM **Run Control Plane** sits outside the three agents. It owns run state, authorization, stage transitions, review gates, immutable artifact versions, task routing, and audit history. The UI reviewer must explicitly approve each stage before the next stage can start. The system must never auto-advance from Stage 1 to Stage 2 or Stage 2 to Stage 3.

The Claims and Rules pipelines are separate. **Claims agents and Rules agents must never communicate directly.** They exchange information only through immutable, versioned artifacts and typed messages routed by the Run Control Plane. A2A is a transport/agent interoperability protocol, not permission to create unrestricted peer communication.

### The design principle

> Build an agent harness, not a fixed sequence of prompts. Each orchestrator must have its own context, tools, working directory, permissions, durable task state, and ability to decide what to inspect or do next. The host application enforces stage boundaries and safety. The model decides the next investigative action within those boundaries.

### What “two pipelines” means in this design

The two substantive work pipelines are:

- **Claims pipeline:** report understanding, source understanding, claim atomization, and reviewer-approved claim state.
- **Rules pipeline:** claim-by-claim source investigation, executable calculation artifacts, and reproducible outputs.

The **Evaluator** is a third sequential stage and independent quality gate across both pipelines. It does not become a second Claims or Rules agent and does not merge their contexts.

---

## 2. The use case and the exact output

TraceWise takes one target PBRER (DOCX or PDF) and a collection of source files (for example CSMR workbooks, case listings, drug-event listings, signal trackers, clinical datasets, exposure tables, supporting reports, and PDFs). Its immediate scope is Section 16.3, but it must understand the target report as a whole because definitions and filters relevant to Section 16.3 may be stated elsewhere.

The intended result is not merely a source-to-section mapping. It is a **claim-level, reproducible calculation dossier**. For every independently verifiable claim in every leaf subsection of Section 16.3, TraceWise should eventually hold:

- The exact source statement and location in the target document.
- A normalized interpretation of what is being counted or asserted.
- The entity and unit: case, event, patient, subject, report, person-year, percentage, or another explicitly defined unit.
- Reporting period, population, subgroup, and inclusion/exclusion criteria where known.
- One concise Stage 1 evidence hint explaining where/how to investigate the claim.
- A Stage 2 evidence bundle, which may contain multiple datasets, worksheets, records, source coordinates, joins, filters, and query evidence.
- A versioned rule specification and inspectable Python implementation where needed.
- Test output, actual execution output, logs, and provenance.
- An independent Stage 3 evaluation result and an auditable status.

A report may state that 300 events occurred among 1,500 cases and also state that this is 20%. If the 20% is merely the deterministic arithmetic consequence of those two already represented figures, it should normally be stored as a derived value linked to the parent claim(s), not as another independently investigated claim. If the percentage has a distinct denominator, population, period, meaning, or independently asserted interpretation, it must remain a separate claim. The system must preserve the exact original report text in either case.

### One claim, one hint, one evidence bundle

Interpret “one claim – one evidence – one hint” as follows:

- **One Claim record** for one independent reported figure/assertion.
- **One concise Evidence Hint** created in Stage 1. It guides investigation but is not proof.
- **One EvidenceBundle object** created/expanded in Stage 2. That single bundle may contain many source files, sheets, rows, cells, joins, and query steps. It must not be restricted to one source row or one file.

This distinction is important: a single reported metric may legitimately depend on both a case-level table and an event-level table. Forcing one row or one file per claim would destroy the real lineage.

---

## 3. Codebase review: what exists and what must change

The current `main` tree already contains a modular agent scaffold. It is not necessary to discard the upload experience, but the existing agent execution is not yet the autonomous, stage-gated harness specified here.

### 3.1 Existing building blocks

| Current path | What it currently provides | Recommended treatment |
|---|---|---|
| `app/main.py` | FastAPI upload, run endpoints, target document access, outline construction, SSE events, claim/knowledge graph endpoints | Keep the application shell and sound upload/document-viewer functionality; refactor into run-control services and explicit stage APIs. |
| `static/index.html`, `static/app.js`, `static/styles.css` | Three-column workspace, report outline/viewer, source inspector, activity feed, mapping/claim panels | Preserve the visual shell and report navigation; redesign the right panel around the Claim Register and stage artifacts; add reviewer gates. |
| `app/agents/base_agent.py` | Common event helper and a wrapper around the custom Bedrock Converse tool loop | Replace/reshape as a Strands agent factory, typed tool wiring, scoped session and event adapters. |
| `app/agents/orchestrator/agent.py` | Current monolithic coordinator, Explorer invocation, parallel subsection handling, claims/evidence/rules/validator calls | Replace with a thin stage-specific orchestration layer. Remove its combined all-stage execution path. |
| `app/agents/explorer/agent.py` | Full-sheet ingestion/profile scaffolding and knowledge-graph Markdown/JSON | Retain useful profiling concepts; rebuild as the Stage 1 source-intelligence capability with full-source coverage, explicit limitations, and a real tool-using Strands agent. |
| `app/agents/claims/agent.py` | Regex-based numeric claim extraction | Replace regex-only extraction with model-assisted structured extraction plus deterministic parsing, evidence locators, deduplication, derivation links, and claim registry tools. |
| `app/agents/evidence/agent.py` | Keyword-based table selection and limited sample retrieval | Replace with an autonomous full-data investigation agent/toolset. Do not use first-five-keyword/first-table heuristics as final evidence. |
| `app/agents/rule_engineer/agent.py` | Heuristic selection of a table/column and a simple distinct-count rule | Replace with a coding-agent loop that can inspect data, write/edit/run Python, test, debug, and publish a structured artifact bundle. |
| `app/agents/validator/agent.py` | Basic required-field checks and numeric equality comparison | Replace with independent artifact review and re-execution in a separate context/environment. |
| `app/agent_tools/source_tools.py` | Bedrock Converse-compatible tool registry | Replace with role-scoped Strands tools and an authorization-aware tool broker. |
| `app/schemas/*.py` | Early Claim/Evidence/MetricRule/Validation Pydantic models | Keep the concept; revise schemas and version them. |
| `app/services/execution_engine.py` | Full-workbook SQLite ingestion, profiling, join candidates, simple rule compiler | Reuse as a prototype substrate after hardening. It is not yet a complete calculation engine: join specifications and numerator/denominator definitions are not fully executed. |
| `app/services/sandbox.py` | Per-run files, read-only chmod attempt, optional Docker execution | Preserve the interface if useful; replace with a fail-closed execution service. Host-process fallback must not be used for untrusted generated code. |
| `app/services/bedrock.py` | Direct boto3 Converse helper and a multi-turn tool-use loop | Use Strands as the primary agent runtime; keep a thin Bedrock configuration/observability adapter only where necessary. |
| `app/services/ag_ui.py` | In-memory event history and custom SSE stream | Preserve domain event concepts; make event delivery durable/replayable and align with the chosen AG-UI client protocol. |
| `tests/test_agent_architecture.py` | Useful initial tests for profiling, joins, claim extraction, metric counting, retry state, sandbox, events, mocked tool loop | Expand heavily with real stage-boundary, security, role-permission, artifact, and end-to-end tests. |

### 3.2 Specific shortcomings that make the current approach infeasible

1. **There are no real human stage boundaries.** `run_autonomous_investigation()` runs Explorer, subsection processing, evidence, rules, and validation in one invocation. The UI cannot approve the output of one stage before the next begins.
2. **Stage 1 and Stage 2 are entangled.** Claim extraction, evidence search, rule generation, and validation happen inside one subsection-processing method. This contradicts the intended two-pipeline separation.
3. **Claims are mostly regex-derived.** Regex is useful for candidate detection, but it cannot reliably understand context, table relationships, cross-references, derivation, or all kinds of reported metrics.
4. **The evidence agent is still heuristic.** It searches a small number of keywords, ranks candidate tables by hits, chooses a primary table, and samples a handful of rows. This is not an autonomous investigation harness.
5. **The rule engineer is not a coding agent.** It guesses an identifier and event column from column names and generates a simple distinct-count rule. It does not autonomously inspect, write, execute, test, debug, and revise code.
6. **The evaluator is not independent.** It checks that a result exists and compares numeric values. It does not independently rerun the actual artifact or validate the conceptual correctness of joins, population, entity, and filters.
7. **The retry loop is not orchestrated.** The validator can return `RETRY_NEEDED`, but the main orchestrator does not execute a complete targeted correction loop. Reviewer guidance is appended to rule assumptions after the current rule has been run; it does not necessarily change the actual query.
8. **The current source tool surface is too permissive.** Raw SQL/`where_clause` parameters and unrestricted generated Python need a policy-enforcing broker, strict identifier handling, parameter binding, and a real sandbox.
9. **The sandbox can fall back to host Python.** If Docker is unavailable or not enabled, generated code runs in the application host process. This must fail closed in production.
10. **State is not durable.** `RUNS`, `ORCHESTRATORS`, and AG-UI history are process-memory structures. A restart can lose the stage, claim, task, and review state.
11. **The new scaffold is not yet using Strands.** The current requirements do not include the Strands Agents SDK, and the current tool loop is a hand-built boto3 Converse loop. The design should adopt Strands as the agent runtime rather than merely relabel the current classes.
12. **The current runtime repository history needs a security review.** The repository is public. Although the latest tree now ignores `runtime/` and source-data extensions, earlier public repository history contained runtime PBRER/CSMR workbooks. Making the repo private and removing files from the current tree does not erase reachable historical Git objects or existing clones. Review and, where required, purge repository history and assess exposure.

### 3.3 What “start fresh” means

Start fresh at the agent harness boundary, not by unnecessarily rewriting every UI and document utility:

- Keep: upload controls, target-document viewer, source-file listing, core extraction adapters after validating their output, and the overall workspace layout.
- Replace: the existing monolithic orchestration path, the current heuristic Claims/Evidence/Rule/Validator logic, the custom agent tool registry, the in-memory claim/run state, and the insecure fallback execution path.
- Do not carry forward the old hardcoded Section 5/7/9 specialist logic or expected example numbers into the new pipeline.
- All generated runtime files, source uploads, logs, and artifacts must be kept outside the Git repository and private storage.

---

## 4. Target architecture

### 4.1 Logical architecture

```text
USER UPLOADS TARGET REPORT + SOURCE FILES
                  |
                  v
        RUN CONTROL PLANE (non-LLM)
   auth / run state / durable artifacts / gates
   versions / approvals / task routing / audit
                  |
                  v
     STAGE 1: CLAIMS ORCHESTRATOR AGENT
       (independent context + Strands tools)
          |                   |
          v                   v
     Claims Agent(s)     Source Intelligence
     leaf subsection    profiling / relationships
          |                   |
          +----------+--------+
                     v
       Claim Registry + source_knowledge.md
       source_knowledge.json + knowledge graph
                     |
             HUMAN REVIEW GATE 1
          Approve / Request changes
                     |
                     v
      STAGE 2: RULES ORCHESTRATOR AGENT
       (independent context + coding tools)
                     |
             one approved claim at a time
                     |
          +----------+-----------+
          |                      |
          v                      v
   Rule Engineer subagent   Analysis/test helpers
          |                      |
          +----------+-----------+
                     v
        Code + tests + result + provenance
           + logs + artifact manifest
                     |
             HUMAN REVIEW GATE 2
          Approve / Request changes
                     |
                     v
       STAGE 3: EVALUATOR ORCHESTRATOR
        (fresh context; independent read)
                     |
          inspect + independently rerun
                     |
             PASS / DISCREPANCY /
          FAIL / INCONCLUSIVE / HUMAN REVIEW
                     |
              HUMAN FINAL REVIEW
                     |
                     v
           APPROVED REVIEW DOSSIER
```

The Run Control Plane is not a fourth autonomous analyst. It is deterministic application code. It must enforce the process even if a model asks to bypass it.

### 4.2 The three principal orchestrators

Each stage gets a separate autonomous agent identity and session/context. Each can plan, call tools, inspect tool results, decide the next step, and finish only when its stage exit criteria are satisfied.

| Orchestrator | Owns | May launch | Must not do |
|---|---|---|---|
| Claims Orchestrator | Stage 1 report understanding, source survey, claim register, evidence hints | Claims specialists per leaf subsection; source profiling/relationship specialists | Generate calculation code or declare claims validated |
| Rules Orchestrator | Stage 2 claim-by-claim investigation, artifact/code generation and self-repair | Rule Engineer and scoped coding/review subagents | Edit approved Stage 1 claims or source originals; communicate directly with Claims agents |
| Evaluator Orchestrator | Stage 3 independent evaluation and discrepancy classification | Read-only verification helpers | Modify Stage 2 artifacts or accept the Rules agent's self-reported PASS |

### 4.3 Independence and memory boundaries

- Each orchestrator has a distinct `agent_id`, session, system prompt, tool profile, scratch workspace, and conversation history.
- Child agents receive a standalone task brief and only the artifact references and context necessary for that task. They do not inherit the parent's full transcript by default.
- Claims and Rules agents cannot call each other, inspect each other's live session, or write into each other's workspace.
- Stage 2 receives a frozen, versioned Stage 1 artifact package. Stage 2 cannot silently modify that package.
- Stage 3 receives the Stage 1 package and Stage 2 artifact manifest through read-only tools. It starts with a fresh session, not a copied Rules conversation.
- The authoritative state is stored in the application database and immutable artifact store. Strands session state is useful for resuming agent context, but it is not the source of truth for claim versions, reviewer approval, or audit history.

### 4.4 Strands usage

Use Strands Agents as the agent runtime and typed Python tools as its capabilities. Use:

- **Agents-as-Tools** for scoped specialists that work under a stage orchestrator and return a bounded result.
- **Graph/workflow patterns** for deterministic subflows within a stage, such as claim extraction -> validation of schema -> register update, or rule plan -> execution -> test -> repair.
- **A2AAgent / A2A protocol** only when an agent is genuinely deployed as a separate service and needs protocol-level remote communication.

Do not use a free-form Swarm as the overall control mechanism. The three reviewer gates, artifact dependencies, and retry budget are known workflow constraints. A graph or explicit state machine is more appropriate for predictable parts of the workflow; the LLM remains autonomous inside each agent's turn loop.

For the initial implementation, use an in-process typed message router with A2A-style request/response envelopes and strict ACLs. Add remote A2A transport only when Claims, Rules, or Evaluator are independently deployed services. Do not call the existing local `Queue` pattern a complete A2A implementation.

---

## 5. Entry point: upload and run initialization

### 5.1 User experience

The user starts where the current application starts:

1. Upload one target report (DOCX/PDF; scanned PDFs must be detected and handled through OCR/document extraction when available).
2. Upload one or more source files (XLSX/XLS/CSV/PDF/DOCX and any explicitly supported additional type).
3. The application validates file types, sizes, malware status, and tenant access.
4. The application stores immutable source objects, calculates SHA-256 hashes, and creates a run.
5. The target report is extracted into a canonical document-block representation suitable for hierarchy and locator resolution.
6. The run is initialized in `AWAITING_STAGE_1`.
7. The reviewer clicks **Start Claims & Source Understanding**. Only then does Stage 1 start.

Do not run all agents immediately when upload completes. Upload/profile operations can validate readability and present a basic file inventory, but they must not silently begin the agentic pipeline.

### 5.2 Run directory and artifact organization

Use a private per-run namespace. Keep it out of the repository.

```text
runs/<tenant_id>/<run_id>/
  input/
    target/<immutable-original>
    sources/<immutable-originals>
  extracted/
    target_document_blocks.json
    source_extraction_manifest.json
  stage_1_claims/
    source_knowledge.md
    source_knowledge.json
    knowledge_graph.json
    schema_profiles.json
    relationships.json
    claims_register.v001.json
    claim_history/
  stage_2_rules/
    claims/<claim_id>/
      plan.md
      evidence_bundle.json
      rule_spec.json
      analysis.py
      tests/
      requirements.lock
      execution.json
      result.json
      provenance.json
      tool_history.jsonl
      stdout.log
      stderr.log
      artifact_manifest.json
  stage_3_evaluation/
    evaluation_report.json
    claims/<claim_id>/evaluation.json
  events/
  audit/
```

This is a logical structure; object storage may use a flat key layout. Every artifact must have an immutable version, checksum, creation time, producing agent/tool, and stage/claim references.

### 5.3 Immutable input rule

- Store each uploaded original unchanged; calculate SHA-256 at ingestion.
- Source files are always mounted/read through read-only capabilities.
- Before and after every code execution, verify source object hashes have not changed. If local file semantics are used, verify that the file is not modified and that the execution environment cannot write to it.
- Never let agent tools accept arbitrary absolute paths. Tools resolve run-scoped logical source IDs and workspace-relative artifact paths.
- If a source is re-uploaded or replaced, create a new run or a new explicit source-set version. Do not mutate the source snapshot underneath an active agent.

---

## 6. Stage 1 — Claims Orchestrator: understand the report, sources, and claims

### 6.1 Objective

Stage 1 must create a complete, reviewable representation of:

1. The target document structure and context.
2. The complete source-file inventory and source knowledge overview.
3. The Section 16.3 hierarchy through the lowest-level subsections.
4. One independently verifiable claim per reported figure/assertion, located at the lowest relevant subsection.
5. One concise, provenance-aware evidence hint per claim.
6. Explicit parent/derived relationships so simple arithmetic derivatives are not duplicated as independent claims.

Stage 1 does **not** calculate and validate every report number. It creates the approved specification of what must be investigated and the information needed to investigate it.

### 6.2 Understand the entire target report

Do not extract only Section 16.3 text and discard the rest. Read the entire target report, including:

- Cover information, product/active substance, reporting period, data lock point, report version, and relevant definitions.
- Table of contents and all heading levels.
- Paragraphs and tables (including nested/merged table structures where possible).
- Footnotes, captions, headers, footers, page numbers, and cross-references where accessible.
- References from Section 16.3 to other sections and relevant definitions elsewhere in the report.
- Explicit statements about population, source category, reporting period, filters, seriousness, initial/follow-up handling, and inclusion/exclusion criteria.

Extract a canonical document-block model. Each block must preserve an exact locator, such as:

- DOCX paragraph index and underlying block index.
- DOCX table index, row, column, cell coordinate, and paragraph within cell where available.
- PDF page number, block/paragraph index, and table cell locator where extracted.
- Source text span / block ID and any OCR confidence where OCR was required.

The heading detector must combine document styles, numbering, table of contents cues, hierarchy, and model interpretation. Do not silently fall back to the first heading if Section 16.3 is not detected. Present an explicit extraction warning and require reviewer correction/confirmation.

Create the complete document outline, then identify Section 16.3 and all descendants. Claims are assigned to the **deepest meaningful subsection**. Parent sections may contain contextual text, but the same child claim should not be duplicated at every ancestor.

### 6.3 Inspect every uploaded source

The source-intelligence subagents survey all uploaded sources, not just files whose names contain a subsection keyword.

For each source file and each worksheet/table, collect:

- Original filename, stored object ID, SHA-256, format, file size, extraction status, and limitations.
- All worksheets, including hidden worksheets where the library permits.
- Header row, metadata/preamble rows, original column names, normalized column names, data types, inferred types, total data rows, blank rows, and extraction warnings.
- Null/blank percentages, distinct counts, duplicate rates, value distributions for relevant categorical fields, date ranges, min/max values, and candidate identifiers.
- Explicit filter notes found in workbook title/preamble, worksheet notes, report headers, export metadata, or source documents.
- Candidate relationships between tables, overlapping key counts, uniqueness on each side, null-key rates, unmatched keys, and tested join cardinality.
- Potential source-level limitations: truncated export, missing dates, duplicate rows, mixed date formats, ambiguous column meaning, unsupported file content, and unparsed images.

Use streaming/chunked ingestion and deterministic analytical queries. Never pass all spreadsheet rows into an LLM context. The agent asks the tools for profiles, samples, summaries, and exact data slices as needed.

### 6.4 Source knowledge files

Generate two artifacts:

**`source_knowledge.md` — reviewer-friendly, concise**

A human-readable overview of every source file, worksheet, fields, record counts, likely purpose, explicit export filters/metadata, candidate relationships, known limitations, and safe investigative clues. It must say whether each filter is explicitly observed, inferred, or unknown.

**`source_knowledge.json` / `knowledge_graph.json` — machine-readable canonical knowledge**

Contains dataset IDs, tables, column profiles, source hashes, relationships, tested cardinalities, limitations, filter evidence, and provenance references. The JSON is the authoritative input to later tools; Markdown is a readable summary, not a query database.

The Explorer must not invent an applied filter merely because it is common in pharmacovigilance. Distinguish:

- `observed`: explicitly stated in source export metadata/report text or proven by a source field/value.
- `inferred`: plausible hypothesis supported by patterns but not confirmed.
- `unknown`: not discoverable from available files.

Every conclusion in `source_knowledge.md` should identify its evidence source or be labelled as an inference.

### 6.5 Claim atomization at the leaf subsection

Claims Agent(s) work at the deepest leaf subsection. Each claim must describe one independently verifiable item. Candidate claim types include:

- Distinct case count.
- Event/reaction count.
- Distinct patient/subject count.
- Source split (spontaneous/solicited/study/literature, etc.).
- Preferred-term/SOC frequency.
- Rate or percentage.
- Exposure value.
- Narrative factual statement that can be checked against evidence.
- Cross-document reconciliation statement.

Never assume that “case”, “event”, “patient”, “subject”, “report”, and “person-year” are interchangeable. Require explicit entity/unit semantics on each quantitative claim.

A claim record should include:

```json
{
  "claim_id": "stable-uuid",
  "section_id": "sec-16.3.x.y",
  "section_number": "16.3.x.y",
  "raw_statement": "Exact original report text",
  "normalized_statement": "Meaning in a normalized form",
  "claim_type": "distinct_case_count",
  "entity_unit": "case",
  "reported_value": 300,
  "unit": "cases",
  "numerator": null,
  "denominator": null,
  "reporting_period": {"start": "...", "end": "...", "source": "observed|inferred|unknown"},
  "population": {"description": "...", "source": "observed|inferred|unknown"},
  "subgroup": null,
  "target_locator": {"document_id": "...", "page": 0, "paragraph": 0, "table": null, "row": null, "cell": null},
  "evidence_hint": {"text": "Concise investigative clue", "observed": [], "inferred": [], "unknowns": [], "source_refs": []},
  "derivation": null,
  "status": "draft",
  "version": 1
}
```

The schema is illustrative; implement strict Pydantic models and schema versions.

### 6.6 Deduplication and derived values (important logic correction)

Do not create a separate claim for every number-shaped substring. The Claims Orchestrator must understand dependencies.

Example: if the report says “300 of 1,500 cases had the event, corresponding to 20%”, and the 20% is exactly `300 / 1,500` for the same time period, population, and unit, then:

- Store the independently meaningful count claims (or a single compound rate claim with numerator/denominator, depending on report semantics).
- Store `20%` as a derived value linked to the relevant parent claims and formula.
- Do not create an independent evidence investigation for the 20% unless it asserts a distinct metric.

Create a separate claim when the percentage has a different population, denominator, period, meaning, or independent regulatory significance. Preserve all original textual representations even when normalized into a derived relationship.

The claim model should support:

- `derived_value` / `derived_expression`.
- `parent_claim_ids`.
- Formula and rounding rules.
- Scope-equivalence assertions (same entity, unit, population, period, inclusion criteria).
- A decision reason: `derived_from_existing_claims` or `independent_claim`.

If scope equivalence cannot be established, do not merge; flag for human review.

### 6.7 One concise hint per claim

The Evidence Hint is not a final rule and must not pretend to be proof. It should be short and useful to Stage 2, e.g.:

> “Likely investigate the case-level export and related drug-event listing; confirm reporting-year bounds, relevant event terms, source category, and whether initial/follow-up records are included. The report describes a distinct-case figure; check case-level deduplication after any event join.”

The hint should identify useful candidate fields/filters and unknowns. It must not hardcode a filter just because it helps reach the reported number. Include observed/inferred/unknown markers and exact report/source references.

### 6.8 Claim Registry tools and state

The Claims Orchestrator needs typed, permission-checked Strands tools to maintain the canonical Claim Register:

- `list_sections()` / `get_leaf_subsections()`.
- `get_target_blocks(section_id)`.
- `list_claims(section_id?)` / `get_claim(claim_id)`.
- `add_claim(claim_payload)`.
- `update_claim(claim_id, patch, expected_version)`.
- `merge_claims(claim_ids, reason, expected_versions)`.
- `split_claim(claim_id, child_claims, reason, expected_version)`.
- `link_derived_value(parent_claim_ids, expression, unit, scope, reason)`.
- `delete_claim(claim_id, reason, expected_version)` — soft-delete/supersede, never erase audit history.
- `set_evidence_hint(claim_id, hint, expected_version)`.
- `validate_claim_register()` — schema, duplicates, hierarchy, missing locators, derived-value integrity.
- `write_stage_artifact(artifact_type, content, schema_version)`.

All mutations must be validated and persisted by application code; the model does not directly edit a JSON file or bypass the registry. Use optimistic concurrency via `expected_version`, stable IDs, append-only change history, and actor/tool metadata. Strands session state may store working notes, but the database Claim Registry is authoritative.

### 6.9 Stage 1 reviewer experience and exit criteria

The reviewer sees:

- Full target section tree and complete report viewer.
- Source inventory, `source_knowledge.md`, and high-level relationship graph.
- Leaf subsection-by-leaf subsection claim list.
- Exact report excerpt/locator for each claim.
- One concise evidence hint per claim, with observed/inferred/unknown labels.
- Derived-value links and any ambiguous/duplicated claim warnings.
- Agent activity showing file/schema inspection and claim additions/edits (not hidden chain-of-thought).

Stage 1 status is `AWAITING_REVIEW` only when:

- Target structure extraction has been completed and section 16.3 selection has been reviewed/confirmed.
- All source files have been inventoried, with ingestion failures explicitly listed.
- The knowledge graph and human-readable source knowledge artifact exist and are versioned.
- All leaf subsections have a claim extraction outcome (claims or explicit “no claims found”).
- Every quantitative claim has unit/entity semantics or is flagged unresolved.
- Every claim has a target locator and one evidence hint.
- Duplicates/derived values are linked or flagged.
- Claim Registry schema validation passes.

The reviewer can approve, edit claims, request changes, or cancel. Approval freezes the Stage 1 artifact versions and hashes. Stage 2 cannot start against a mutable draft.

---

## 7. Stage 2 — Rules Orchestrator: autonomous coding and artifact production

### 7.1 Objective

The Rules Orchestrator receives the reviewer-approved Stage 1 bundle and works through claims one by one. It is a coding agent, not a fixed metric-template generator.

For each claim it must autonomously:

1. Read the claim and evidence hint.
2. Inspect the source knowledge graph and original source schema.
3. Decide what further data exploration is necessary.
4. Query the complete analytical dataset and inspect representative records.
5. Test candidate joins and cardinalities.
6. Discover filters/population criteria from report context, source metadata, and records.
7. Write a short plan and rule specification.
8. Write Python analysis code and tests (or use an approved deterministic query API for simple cases; Python artifact remains the reproducible deliverable when requested).
9. Execute in a restricted sandbox.
10. Inspect exit code, stdout, stderr, generated files, tests, and computed values.
11. Revise the code/rule after failures or inconsistent findings.
12. Produce a final per-claim artifact bundle with exact provenance and unresolved assumptions.

The agent must decide what to inspect next. It must not be forced through a fixed list of event terms, dates, seriousness flags, or denominators.

### 7.2 Coding-agent tools (Crush-inspired)

Give the Rules Orchestrator a real, explicit toolset:

**Workspace/navigation**
- `list_workspace_files`, `glob_files`, `grep_workspace`, `read_file`, `read_source_metadata`, `read_artifact`.

**Source investigation**
- `list_source_files`, `get_dataset_manifest`, `get_sheet_schema`, `profile_column`, `search_column_values`, `sample_rows`, `find_candidate_joins`, `test_join_cardinality`, `execute_readonly_query`, `get_row_provenance`.

**Code authoring**
- `write_file`, `edit_file`, `multi_edit`, `delete_workspace_file`, `diff_file`, `read_file_version`.

**Execution/testing**
- `run_python`, `run_pytest`, `get_job_status`, `get_job_output`, `inspect_execution_artifacts`, `hash_artifact`.

**Coordination**
- `dispatch_rule_subagent`, `get_subagent_status`, `collect_subagent_report`, `cancel_subagent`, `request_claim_clarification` (routes only to Run Control Plane, not Claims agent).

Each tool must have a strict Pydantic input schema, bounded output, correlation ID, audit event, authorization policy, timeout, and typed result. The model receives no direct AWS credentials and no arbitrary host filesystem/network access.

### 7.3 File-editing semantics to borrow from Crush

Use the useful engineering principles from Crush:

- A child agent receives a self-contained task prompt and an explicit scope.
- Read-only is the default. Write access is granted only for a specific claim workspace or artifact directory.
- Before editing an existing file, require the agent to read its latest version. If the file changed since its last read, require a fresh read.
- Prefer exact-match edits; if there are multiple matches, fail with a diagnostic rather than guessing.
- Every edit records a diff, before/after hash, agent/tool identity, and artifact version.
- Parallel writable subagents must have non-overlapping workspaces.
- Long-running jobs have durable status and can be cancelled/resumed.
- The orchestrator receives a bounded report from each child rather than inheriting every token of its transcript.

Do not copy Crush's whole terminal app or grant a generic shell with broad permissions. Its relevant principles are context isolation, tools, permissions, session lifecycle, scoped writes, auditability, and loop detection.

### 7.4 Claim-by-claim work loop

Recommended flow for every claim:

```text
LOAD APPROVED CLAIM + STAGE 1 HINT
            |
            v
READ SOURCE KNOWLEDGE + RELEVANT SCHEMAS
            |
            v
INVESTIGATE FULL DATA / TEST JOINS / PROFILE FILTERS
            |
            v
WRITE PLAN + RULE SPEC + PYTHON + TESTS
            |
            v
EXECUTE IN ISOLATED SANDBOX
            |
            v
INSPECT OUTPUT, ERRORS, TESTS, PROVENANCE
            |
       +----+----+
       |         |
   incomplete  coherent
       |         |
       v         v
EDIT / RETEST  PUBLISH ARTIFACT BUNDLE
       |
       +---- bounded loop guard / budget ----+
```

Do not tell the agent to modify filters until the calculated result matches the report. It must derive filters from documented definitions and actual source semantics, not optimize against a target figure.

### 7.5 Generated artifact contract

Each claim workspace should produce at least:

| Artifact | Purpose |
|---|---|
| `plan.md` | Human-readable investigation and calculation plan, assumptions, and next steps |
| `evidence_bundle.json` | Source tables, field mappings, joins, filters, query IDs, counts, samples, provenance, and limitations |
| `rule_spec.json` | Structured, versioned description of the calculation logic |
| `analysis.py` | Reproducible Python implementation; not merely a model explanation |
| `tests/` | Unit/integration tests for the calculation and important edge cases |
| `requirements.lock` | Pinned execution dependencies or environment manifest |
| `execution.json` | Execution command, image digest, exit code, runtime, test results, and resource use |
| `result.json` | Computed value, unit, numerator/denominator, intermediate counts, and summary |
| `provenance.json` | Source file hashes, worksheet/table, row/cell references, query, joins, record counts, and evidence digest |
| `stdout.log` / `stderr.log` | Inspectable execution logs |
| `tool_history.jsonl` | Ordered tool calls and results, excluding secrets and sensitive row payloads where possible |
| `artifact_manifest.json` | Hash and version of every output file; producer and timestamp |

The rule specification should preserve entity semantics and support joins, filters, deduplication, numerator/denominator, grouping, and derivation. It may be a declarative representation plus Python implementation. Do not constrain every metric to a small DSL if the use case requires complex logic; but always make the logic inspectable and reproducible.

### 7.6 Evidence and rule details

The evidence bundle should answer:

- Which exact source datasets are used?
- Which fields represent the entity, event, date, source type, and other conditions?
- What is the source of every filter (target report, export metadata, user instruction, or inference)?
- What rows are selected by each filter, and how many remain after each step?
- Are joins one-to-one, one-to-many, or many-to-many? Did joins multiply records?
- Are the counts of source rows, distinct entities, matched events, and unmatched keys preserved?
- What is the deduplication key and why?
- What are the original source coordinates for a sample and, where appropriate, full matched-record lineage?

For case-level and event-level exports, the agent must explicitly test the relation before computing distinct case counts. A one-to-many join can be correct for event counts but can inflate counts if the wrong aggregation is used. Many-to-many relationships require explicit analysis and must not be silently accepted.

### 7.7 Retry, loop engineering, and bounded autonomy

Self-repair belongs in the Rules Orchestrator. It may inspect failures and amend its code, but every action remains auditable and bounded.

Required controls:

- Maximum tool calls per claim attempt.
- Maximum runtime, CPU/memory, and output size per execution.
- Maximum total agent/model turns and token/cost budget per claim and run.
- A configurable maximum number of code-repair attempts.
- Repeated tool-call signature detection over a sliding window (for example, detect repeated identical tool name/input/result sequences).
- If the same script and same error recur without a meaningful change, stop and report the loop rather than repeating.
- Each retry must include a short rationale and a code/rule diff.
- Preserve failed attempts and their logs; do not overwrite the history with only the final successful attempt.

Default retry policy should be explicit and configurable. A sensible starting point is **one initial execution plus at most two automatic repair cycles** for each claim; allow a stricter or more generous policy by configuration. If product language means “three retries after the first attempt,” configure three repair cycles explicitly. Keep the Rules Orchestrator's self-repair budget separate from the Evaluator's independent rework budget.

### 7.8 Subagents and workspace permissions

The Rules Orchestrator may dispatch specialists for independent scopes, such as:

- Source schema investigation for a specific claim.
- Candidate join/cardinality analysis.
- Independent code review of one claim's script.
- Test fixture generation for one claim.

Each subagent must receive:

- A self-contained task brief.
- Claim ID and immutable Stage 1 artifact version.
- Exact read/write scope.
- Allowed tools and expected output schema.
- A deadline, resource budget, and return format.

Default subagents to read-only. Grant write only when the subagent owns a unique claim workspace. The parent owns the shared artifact manifest. Two write-enabled agents may not edit the same files concurrently.

### 7.9 Stage 2 reviewer experience and exit criteria

The reviewer sees per claim:

- Plan and evidence bundle.
- Source filters, joins, counts before/after, and exact row/cell lineage.
- Rule specification.
- Python source and tests.
- Execution result, stdout/stderr, test status, generated artifacts, and code hash.
- Assumptions, unresolved questions, and retry history.

Stage 2 is ready for review only when every approved Stage 1 claim has one of:

- A complete reproducible artifact bundle.
- An explicit `NOT_COMPUTABLE` / `NEEDS_HUMAN_INPUT` outcome with explanation.
- A deliberate `UNRESOLVED` result after the retry budget.

Do not mark a claim “compiled” merely because a script or JSON file exists. A successful run is not yet independent validation. Stage 2 status must remain `ARTIFACTS_READY` or `UNRESOLVED`, not `VALIDATED`.

The reviewer can inspect, approve, or request Stage 2 changes. Stage 3 starts only after explicit approval and a frozen Stage 2 artifact manifest.

---

## 8. Stage 3 — Evaluator Orchestrator: independent evaluation

### 8.1 Objective

Evaluator starts in a new context. It gets read-only access to:

- Approved Stage 1 Claim Register and source knowledge artifacts.
- Original immutable sources through restricted read/query tools.
- Stage 2 code, tests, rule specs, execution logs, outputs, and provenance.

It does not inherit the Rules Orchestrator's transcript or working memory. It must not assume a Rules result is correct because the Rules Orchestrator says it succeeded.

### 8.2 Independent checks

For every claim, evaluate:

1. **Claim linkage:** Does the artifact calculate the exact claim ID/version and target statement?
2. **Target locator:** Does the reported figure actually occur at the cited document location?
3. **Unit/entity:** Is the result a count of cases, events, patients, subjects, reports, exposure, or something else? Does it match the claim?
4. **Dataset selection:** Are the relevant source files/tables used? Are missing or competing datasets considered?
5. **Population/period:** Are the filters supported by the report or source metadata? Are inferred constraints clearly labelled?
6. **Join correctness:** Is the join cardinality tested? Could duplicate expansion or lost keys distort the result?
7. **Numerator/denominator:** Are these defined correctly and consistently? Are distinct entities used where required?
8. **Execution:** Does the generated code run in a clean environment with the pinned dependencies?
9. **Independent reproducibility:** Can Evaluator independently re-run the artifact or reconstruct the calculation using read-only tools and obtain the same result?
10. **Provenance:** Do source hashes, sheet names, source row coordinates, query parameters, output hashes, and audit records reconcile?
11. **Integrity/safety:** Did code access only its permitted workspace and source snapshot? Were originals unchanged? Were sensitive identifiers kept out of logs and model prompts as required?
12. **Claim support:** Does the evidence substantiate the statement, not merely cite a row that contains a similar word?

The Evaluator should use a separate clean sandbox and separate role credentials. It may run a copy of the artifact against the same immutable inputs but must not mutate the Rules workspace or its published bundle.

### 8.3 Evaluation statuses

Use precise statuses rather than a single `verified` boolean:

- `PASS`: all mandatory checks pass and independent reproduction succeeds.
- `DISCREPANCY`: computation is reproducible but does not reconcile with the report figure, or the report/source definitions differ.
- `FAIL`: code, lineage, population, join, unit, or evidence is demonstrably incorrect.
- `INCONCLUSIVE`: available evidence does not support a decisive conclusion.
- `NEEDS_HUMAN_REVIEW`: ambiguity requires a reviewer or domain definition.
- `UNRESOLVED`: configured correction budget is exhausted.

A numerical mismatch is not automatically a code failure. The report may contain an error, sources may not cover the same population/time period, or a definition may be ambiguous. The Evaluator must classify the cause rather than simply force a match.

### 8.4 Critical fallacy to avoid: target-fitting

**Never instruct the Rules Orchestrator to keep changing filters until the result equals the PBRER's reported number.** That would create a target-fitting loop and could produce a false but matching calculation.

The target value is a reconciliation reference, not an optimization objective. If the result differs:

- Inspect evidence and filter provenance.
- Check source coverage and reporting-period definition.
- Check entity type and distinctness.
- Check join multiplication and denominator construction.
- Check whether Stage 1 atomized or interpreted the claim incorrectly.
- Determine whether the target report or the source extraction is internally inconsistent.

Evaluator returns a structured discrepancy diagnosis to the Run Control Plane. It may request a targeted Stage 2 revision, or Stage 1 reopening if the claim itself is ambiguous. It does not directly message or edit the Claims/Rules agent context. A returned-to-stage correction creates a new artifact version and requires the appropriate reviewer gate again.

### 8.5 Stage 3 outputs and final review

Create:

- `evaluation_report.json` for the whole run.
- One `evaluation.json` per claim with each check, evidence, independent rerun details, discrepancy category, and outcome.
- An audit record linking Stage 1, Stage 2, and Stage 3 artifact versions.
- A final reviewer-facing dossier / export view.

Human final sign-off is still required. `PASS` means the software's evaluation criteria passed; it does not mean the report is a regulator-approved submission or replace a qualified pharmacovigilance review.

---

## 9. Communication architecture and A2A rules

### 9.1 Communication policy

```text
Claims Orchestrator  ---> Claims specialist agents
        |
        +-- publishes Stage 1 artifacts --> Run Control Plane
                                           |
                                           v
                                  Stage 2 Rules Orchestrator
                                           |
                                           +--> Rule Engineer subagents
                                           |
                                           +-- publishes artifacts --> Run Control Plane
                                                                           |
                                                                           v
                                                              Stage 3 Evaluator
```

There is no direct Claims Agent <-> Rules Agent connection. Evaluator also has no direct authority to modify the other agents' workspace.

### 9.2 Typed message envelope

Every internal or A2A message should include:

```json
{
  "message_id": "uuid",
  "run_id": "uuid",
  "stage": "claims|rules|evaluation",
  "sender_agent_id": "...",
  "recipient_agent_id": "...",
  "intent": "...",
  "correlation_id": "...",
  "causation_id": "...",
  "claim_id": "optional",
  "section_id": "optional",
  "artifact_refs": [],
  "payload_schema_version": "1.0",
  "created_at": "ISO-8601",
  "expires_at": "ISO-8601"
}
```

Payloads should contain references to immutable artifacts, not huge raw datasets. All message routing is authorized by a policy layer. A tool call from a Rules agent to a Claims agent must be rejected at the broker, logged, and returned as a permission error.

### 9.3 A2A implementation rule

Start with a local typed message router for agent/task coordination. Add remote A2A protocol only when you need separately deployed services. The existence of a typed message class or queue does not by itself make a service a remote A2A agent.

---

## 10. Durable state, artifacts, and stage gates

### 10.1 Run state machine

Recommended run states:

```text
UPLOADED
  -> READY_FOR_STAGE_1
  -> STAGE_1_RUNNING
  -> STAGE_1_AWAITING_REVIEW
  -> STAGE_1_APPROVED
  -> STAGE_2_RUNNING
  -> STAGE_2_AWAITING_REVIEW
  -> STAGE_2_APPROVED
  -> STAGE_3_RUNNING
  -> STAGE_3_AWAITING_REVIEW
  -> FINAL_APPROVED
```

Alternative terminal/branch states:

- `STAGE_FAILED`
- `REVIEW_CHANGES_REQUESTED`
- `NEEDS_HUMAN_INPUT`
- `RETURNED_TO_STAGE_1`
- `RETURNED_TO_STAGE_2`
- `CANCELLED`
- `UNRESOLVED`

Transitions must be validated by application code. Agents cannot change the run-level stage state directly. Approval must include authenticated reviewer identity, approved artifact version/hash, timestamp, and optional reviewer note.

### 10.2 Dependency and invalidation rules

- Stage 2 references the exact approved Stage 1 claim-register version and source knowledge version.
- Stage 3 references exact Stage 1 and Stage 2 artifact manifest versions.
- Editing a Stage 1 claim after approval invalidates affected Stage 2 and Stage 3 artifacts. Do not leave downstream results marked current.
- Editing a Stage 2 rule/code artifact after its approval invalidates affected Stage 3 results.
- A correction creates new artifact versions; never overwrite the previous approved version.
- Reopening one claim should invalidate only its dependent artifacts and any shared artifacts whose dependency graph includes that claim.

### 10.3 Reviewer-gated HTTP API (illustrative)

| Endpoint | Operation | Guard |
|---|---|---|
| `POST /api/runs` | Upload target + sources and create run | Authenticated tenant; immutable source manifest |
| `POST /api/runs/{id}/stages/claims/start` | Start Stage 1 | Run is `READY_FOR_STAGE_1` |
| `GET /api/runs/{id}/stage-1/claims` | Read Claim Register | Tenant/run access |
| `GET /api/runs/{id}/stage-1/source-knowledge` | Read Markdown/JSON knowledge | Tenant/run access |
| `POST /api/runs/{id}/stages/claims/approve` | Approve or request Stage 1 changes | Authenticated reviewer + expected version/hash |
| `POST /api/runs/{id}/stages/rules/start` | Start Stage 2 | Stage 1 approved and frozen |
| `GET /api/runs/{id}/stage-2/claims/{claim_id}/artifacts` | Inspect rule artifacts | Tenant/run access |
| `POST /api/runs/{id}/stages/rules/approve` | Approve or request Stage 2 changes | Authenticated reviewer + manifest hash |
| `POST /api/runs/{id}/stages/evaluation/start` | Start Stage 3 | Stage 2 approved and frozen |
| `GET /api/runs/{id}/stage-3/evaluation` | Read evaluation results | Tenant/run access |
| `POST /api/runs/{id}/stages/evaluation/approve` | Final human approval | Authenticated reviewer + evaluation hash |
| `POST /api/runs/{id}/stages/{stage}/cancel` | Cancel active stage | Authorized operator/reviewer |
| `GET /api/runs/{id}/events?cursor=...` | Replay durable events | Tenant/run access |

All start/approve operations must be idempotent. Use expected artifact versions to avoid approving a stale UI view.

---

## 11. UI implementation

Preserve the current three-column workspace and report viewer.

### Left panel — document structure

- Entire target hierarchy, with Section 16.3 highlighted.
- Lowest-level subsection tree.
- Parsing warnings and human corrections.

### Centre panel — report and activity

- Full target report, including tables.
- Current stage orchestrator and scoped subagents.
- Real tool activity: reading source, profiling a sheet, writing a script, running tests, inspecting an artifact, requesting reviewer input.
- Artifact tray with versions and hashes.
- Show concise operation summaries, not private model chain-of-thought.

### Right panel — Claim Register

Claims grouped by leaf subsection. Each row shows:

- Claim statement and reported value/unit.
- Evidence hint (Stage 1) or evidence bundle status (Stage 2).
- Rule artifact and execution status.
- Evaluator status.
- Derived-from links where applicable.

Selecting a claim opens a lineage drawer with:

1. Target report excerpt and exact location.
2. Stage 1 hint and its observed/inferred/unknown basis.
3. Source dataset(s), worksheet(s), and column mappings.
4. Filter and join sequence, counts before/after, exact row/cell locators.
5. Rule spec, Python source, tests, logs, result, and provenance.
6. Evaluator checks, independent rerun, discrepancies, and review history.

### Stage controls

Buttons should be explicit and stage-aware:

- **Start Stage 1: Understand report & sources**
- **Approve Stage 1 and initialize Stage 2**
- **Approve Stage 2 and initialize Evaluator**
- **Approve final evaluation**

Disabled states must explain which artifact or reviewer action is required. No hidden automatic stage advance.

---

## 12. AWS deployment and security model

### 12.1 Recommended production layout

| Component | Recommended AWS service / responsibility |
|---|---|
| Web UI/API | FastAPI service on ECS Fargate behind ALB/API Gateway; Cognito or enterprise OIDC for identity |
| Workflow gates | Step Functions Standard Workflow or an equivalent durable state machine |
| Agent tasks | ECS Fargate workers for stage orchestrators and isolated execution jobs |
| Queueing | SQS for background job dispatch/retries where needed |
| Original sources and artifacts | Private S3 bucket/prefix per tenant/run, versioning, SSE-KMS, Block Public Access |
| Run/claim/audit state | RDS/Aurora PostgreSQL (local dev may use SQLite) |
| Analytical engine | DuckDB/Parquet or another controlled per-run analytical engine; retain SQLite for local/simple cases only if it meets volume needs |
| LLM | AWS Bedrock Claude model/inference profile through Strands |
| Logs and metrics | CloudWatch structured logs/metrics, OpenTelemetry/X-Ray tracing |
| Secrets | Secrets Manager/SSM and task roles; never expose credentials to model context or code sandbox |

Do not introduce Neptune merely because the application uses the phrase “knowledge graph.” A structured JSON graph and relational metadata database are sufficient initially. Add a graph database only after observed relationship complexity and query needs justify it.

### 12.2 Human review pauses

For production, Step Functions Standard Workflows are a good fit for explicit human approval pauses. A stage task can wait for an authenticated reviewer callback using a task-token pattern; the UI calls the application API, which authorizes the reviewer and returns the appropriate success/failure to the workflow. The token must be treated as a secret and never be visible to an LLM or browser.

For local development, a durable database-backed state machine can emulate the same gate semantics. The UI contract should not depend on whether the gate is implemented by Step Functions or the local coordinator.

### 12.3 Execution isolation

Generated Python is untrusted code. Production execution must not fall back to the web/API host process.

Use one isolated execution task/container per claim attempt or suitably isolated batch, with:

- Non-root user.
- Read-only source mount/object access.
- Writable workspace only for that claim's artifacts.
- No general network egress; allow only required storage/logging endpoints through controlled VPC endpoints/security groups.
- No AWS credentials except a narrowly scoped task role if artifact I/O requires it.
- Memory, CPU, runtime, process count, file size, output size, and disk quotas.
- Pinned base image by digest and locked Python dependencies.
- Container/task termination and cleanup after execution.
- Separate IAM task roles for agent orchestration, analytical data reads, and sandbox artifact writes.

For Docker-based local execution, use `--network none`, read-only source mounts, non-root user, read-only root filesystem where supported, dropped capabilities, no-new-privileges, PID/memory/CPU limits, and no inherited host credentials. If the isolation backend is not available, fail closed and do not execute code.

### 12.4 Privacy and PHI

- Keep S3 private with SSE-KMS and restrictive bucket policies.
- Use tenant-scoped object keys and application-level authorization on every run/artifact query.
- Avoid sending raw case/patient identifiers to the model unless demonstrably necessary and approved. Prefer pseudonymous, run-scoped keys for model reasoning while preserving exact identifiers and source mapping in the protected analytical layer.
- Redact secrets and unnecessary identifiers from prompts, tool outputs, stdout/stderr, telemetry, and generated Markdown.
- Never put source rows, PHI, task tokens, credentials, or connection strings in public GitHub artifacts or CI logs.
- Define retention, deletion, access audit, and backup policy before production onboarding.

---

## 13. Suggested codebase reset / replacement map

A target layout could be:

```text
app/
  main.py                         # FastAPI shell only
  api/
    runs.py
    stages.py
    claims.py
    artifacts.py
    events.py
    review.py
  control_plane/
    run_state.py                  # deterministic state machine
    approvals.py
    task_router.py
    dependency_invalidator.py
    message_acl.py
  agents/
    base.py                       # Strands factory/session/events
    claims_orchestrator/
      agent.py
      prompt.md
      claim_tools.py
      document_understanding.py
      claim_atomizer.py
      source_survey.py
    rules_orchestrator/
      agent.py
      prompt.md
      coding_tools.py
      subagent_dispatch.py
      retry_policy.py
    evaluator_orchestrator/
      agent.py
      prompt.md
      evaluator_tools.py
      independent_checks.py
  tools/
    document_tools.py
    source_tools.py
    claim_registry_tools.py
    workspace_tools.py
    execution_tools.py
    artifact_tools.py
  schemas/
    run.py
    section.py
    claim.py
    evidence_hint.py
    evidence_bundle.py
    rule_artifact.py
    evaluation.py
    messages.py
  services/
    storage.py
    database.py
    extraction.py
    analytics.py
    sandbox_client.py
    bedrock.py
    event_stream.py
  prompts/
    claims_orchestrator.md
    claims_specialist.md
    rules_orchestrator.md
    rule_engineer.md
    evaluator_orchestrator.md
  tests/
```

The exact folder naming is flexible; ownership and boundaries are not.

### Keep, rewrite, or remove

- Keep and harden `extractors.py` and the report viewer's canonical block rendering.
- Keep `ExecutionEngine` only as a prototype; fix its schema/type handling, read-only query policy, bound parameters, joins, denominator support, provenance, and concurrency before production.
- Replace `AgentToolRegistry` with role-scoped Strands tools.
- Replace the combined `MultiAgentOrchestrator.run_autonomous_investigation()` path with the durable three-stage control plane and three autonomous orchestrators.
- Replace current `ClaimsAgent`, `EvidenceDiscoveryAgent`, `RuleEngineerAgent`, and `ValidatorAgent` internals; do not migrate their heuristic decisions as rules.
- Replace host-process sandbox fallback with a fail-closed executor.
- Replace process-memory-only run/event state with database/object-store persistence.
- Keep the UI shell but remove the assumption that all work happens under one “Launch Agents” button.

---

## 14. Implementation roadmap

### Milestone 0 — Repository and data safety

- Make the GitHub repository private while historical runtime data is assessed.
- Audit Git history, releases, branches, Actions artifacts, and clones for any sensitive source data or credentials.
- Remove sensitive objects from reachable history where necessary; rotate any exposed secrets.
- Ensure `runtime/`, uploads, databases, generated Python, source data, and artifacts are outside Git.
- Establish local dev data fixtures containing synthetic/de-identified examples only.

**Exit:** no real source files or secrets in repository history under the accepted security policy; runtime storage defaults outside repository; source immutability test passes.

### Milestone 1 — Run Control Plane and upload foundation

- Refactor upload and extraction to create immutable source manifests and target document blocks.
- Introduce durable run/stage/approval/claim/artifact records.
- Implement stage start/approve/reject APIs and idempotent transitions.
- Add artifact version hashes and dependency invalidation.
- Remove the old one-click `launch-agents` combined workflow.

**Exit:** uploading creates a run in `READY_FOR_STAGE_1`; no agents run before explicit click; application restart does not lose stage/approval state.

### Milestone 2 — Strands harness and permissions

- Add Strands Agents SDK and Bedrock configuration.
- Implement agent factory with explicit agent IDs, sessions, stage-specific system prompts, tool scopes, structured outputs, and event hooks.
- Implement read/write workspace policy, tool permission broker, safe cancellation/resume, task timeouts, and loop detection.
- Implement local typed message router and ACL tests; no Claims<->Rules route.

**Exit:** a mocked and a Bedrock-backed Strands agent can inspect files and call registered tools; denied tools cannot be bypassed through tool arguments.

### Milestone 3 — Stage 1 Claims Orchestrator

- Build canonical full-report block and locator model.
- Build full-source survey and knowledge graph.
- Generate `source_knowledge.md` and JSON artifacts.
- Implement Claim Registry tools and versioned edit history.
- Implement leaf-subsection claim extraction, hints, derived-value handling, and claim deduplication.
- Add Stage 1 review UI and approval gate.

**Exit:** reviewer can inspect, add/edit/remove/split/merge claims, approve a frozen Stage 1 package, and no Stage 2 activity begins before approval.

### Milestone 4 — Stage 2 Rules coding harness

- Build source investigation tools and full-dataset query engine.
- Build claim-scoped workspace and file manipulation tools.
- Build secure isolated Python execution service.
- Implement autonomous plan -> inspect -> write -> execute -> test -> inspect -> repair loop.
- Implement subagent dispatch with scoped read/write access and artifact reporting.
- Publish per-claim artifact bundle and Stage 2 review UI.

**Exit:** representative claims produce reproducible code, tests, results, row/cell provenance, source hashes, and inspectable retry history; source originals remain unchanged.

### Milestone 5 — Stage 3 independent Evaluator

- Create fresh Evaluator session and read-only tool profile.
- Independently rerun artifacts in a separate sandbox.
- Implement claim/units/population/filters/joins/denominator/provenance/integrity checks.
- Implement discrepancy classification and targeted return-to-stage request through control plane.
- Implement final reviewer approval.

**Exit:** deliberate wrong rules, wrong joins, wrong units, mismatched populations, missing provenance, and nondeterministic code are rejected; a code change never auto-passes without re-evaluation.

### Milestone 6 — AWS production hardening

- Deploy API and orchestrators to ECS Fargate.
- Add S3 KMS object storage, RDS/Aurora state, Step Functions gates, queueing, task roles, secret management, VPC/network controls, and CloudWatch/OpenTelemetry observability.
- Add retention and tenant isolation policies.
- Load test full workbooks, large source sets, and long-running tool loops.

**Exit:** multi-tenant run isolation, task resumption, cancellation, storage encryption, audit retention, and sandbox isolation pass integration tests.

---

## 15. Acceptance criteria and test strategy

### Stage 1 acceptance

- Entire target document has a complete outline and block locators.
- Section 16.3 and leaf subsections are correctly identified or explicitly flagged for reviewer correction.
- Every source file and worksheet is inventoried; row counts are full-dataset counts, not preview counts.
- Candidate joins show uniqueness/cardinality and unmatched-key counts.
- Explicit filters are separated from inferred filters and unknowns.
- `source_knowledge.md` and canonical JSON artifacts are generated.
- Claims are leaf-subsection scoped, have exact target locators, entity/unit semantics, and one concise hint.
- Derived percentages are linked to parent claims when scope equivalence is proven; ambiguous ratios are not silently merged.
- Claim Registry tools enforce versioned mutations and append-only history.
- Reviewer gate prevents Stage 2 without a matching approved artifact hash.

### Stage 2 acceptance

- Rules Orchestrator can independently choose investigative tools and next actions.
- It can create, edit, read, list, diff, execute, test, and inspect artifacts in its claim workspace.
- It can spawn scoped subagents and collect bounded results.
- It can diagnose code errors and revise code within a finite budget.
- It records source hashes, joins, filters, counts, queries, row/cell provenance, environment, execution result, and artifact hashes.
- It never modifies original source data or Stage 1 approved artifacts.
- A host execution fallback is impossible when the sandbox is unavailable.
- Stage 2 reviewer gate prevents Stage 3 from starting without a matching approved artifact manifest.

### Stage 3 acceptance

- Evaluator starts with a fresh session and read-only access.
- It independently executes or reconstructs calculations.
- It detects wrong entity type, duplicate join inflation, wrong date bounds, wrong filters, wrong numerator/denominator, missing evidence, broken provenance, and modified input files.
- It does not force the output to match the target report.
- It produces per-claim evaluation status and whole-run report.
- Changes to Stage 1/2 artifacts invalidate dependent evaluation.
- Final approval is a reviewer action, not an agent status.

### Security and reliability tests

- Agent role ACL: Claims agent cannot call Rules agent; Rules agent cannot edit claim register; Evaluator cannot write artifacts.
- Path traversal and cross-tenant workspace access denied.
- SQL injection/raw multi-statement attempts rejected.
- Sandbox missing/unavailable causes fail-closed behavior.
- Source file hash before/after execution is identical.
- Generated code cannot reach host credentials or unrestricted network.
- Agent cancellation kills child jobs; no orphaned container.
- Repeated identical tool-call/error sequences trigger loop detection.
- Tool outputs and event logs do not leak secrets or unnecessary identifiers.
- Stage approval endpoints are idempotent and reject stale expected versions.
- API restarts do not lose run state or event replay position.

---

## 16. Key failure modes and how the architecture prevents them

| Failure mode | Required design response |
|---|---|
| Model invents filters based on common PV practice | Every filter carries `observed`, `inferred`, or `unknown` provenance; validator checks evidence source. |
| Matching keywords but selecting wrong table | Explorer knowledge graph + complete data profiling + claim-specific investigation; no first-table fallback. |
| Counting events when claim means distinct cases | Explicit entity type and aggregation; evaluator checks entity semantics and denominator. |
| Join inflates denominator | Cardinality test, pre/post join row counts, distinct entity checks, independent evaluator. |
| Report's number is wrong or source scope differs | Discrepancy is reported; do not target-fit the code. |
| Percentage duplicates an existing count | Derived-value graph and scope-equivalence test. |
| Code overwrites source file | Read-only source mounts, sandbox policy, hash verification, no host path tool. |
| Child agents overwrite shared files | One claim workspace per writable worker; path-scope ACL; parent-owned manifest. |
| Stage 2 reads a draft claim after approval | Immutable artifact hash/version; every tool invocation checks allowed snapshot. |
| LLM marks stage completed without artifacts | Control plane validates exit criteria and manifest before stage gate. |
| Repeated tool loop | Tool-call signature detection, bounded budgets, cancellation, persistent attempt history. |
| Process restart loses progress | Durable run DB, object storage, agent session persistence, replayable events. |
| Agent-to-agent bypass | Central message broker and ACL; no direct Claims/Rules route. |

---

## 17. Master engineering prompt for the implementation agent

The following is the implementation brief to give to a coding agent working on TraceWise. It is intentionally explicit so the agent does not return to the current coupled/heuristic architecture.

### ROLE

You are the principal engineer building TraceWise, an autonomous pharmacovigilance evidence and calculation harness. You are implementing a three-stage sequential workflow inspired by the engineering principles of Charmbracelet Crush: autonomous tool use, separate agent contexts, scoped subagents, read/write permissions, reliable file tools, execution feedback, persistent sessions, event history, cancellation, and loop detection. You are not building a generic coding terminal and must not copy Crush's full TUI or unrestricted shell model.

### SOURCE OF TRUTH

Before editing, inspect the current TraceWise repository and identify the current upload flow, target-document extraction, source profile/execution engine, frontend, event stream, and every agent implementation. The current `main` commit reviewed for this specification is `15ebf04cc0ccd41b7b828b5e25444ded6eaf1cc8`. Verify the live branch before implementing, because the repository can change.

Treat the existing implementation as prototype code. Do not trust the README's capability claims without checking the code. Do not transplant hardcoded Section 5/7/9 rules, filenames, sample numbers, keyword filters, or status-setting logic into the new architecture. Preserve only sound upload/document-viewer/extractor and data-engine primitives after auditing them.

### PRODUCT GOAL

From the moment a user uploads one target PBRER plus source files, run exactly three sequential stages:

1. Claims Orchestrator: understand the entire target document and all source files; identify Section 16.3 and its full hierarchy; extract claims only at the lowest-level subsection; create one concise evidence hint per claim; store claims in an editable versioned Claim Registry; and produce `source_knowledge.md` plus structured source knowledge/relationship artifacts.
2. Rules Orchestrator: for every reviewer-approved claim, act as a Claude-Code-like coding agent that independently inspects source data, writes/edits Python and tests, executes, inspects output/errors, repairs, and produces reproducible calculation/evidence artifacts. It may spawn scoped specialist subagents.
3. Evaluator Orchestrator: in a fresh context and read-only workspace, independently inspect and rerun the Rules artifacts, check that claims, evidence, filters, joins, units, results, and provenance match, then issue a structured evaluation report.

A reviewer explicitly approves Stage 1 before Stage 2, and Stage 2 before Stage 3. Final evaluation also requires human sign-off. No automatic stage transitions.

### NON-NEGOTIABLE AGENT BOUNDARIES

- There are three principal autonomous orchestrators, one for each stage.
- Each orchestrator has an independent Strands agent identity/session/context, tools, system prompt, workspace, and permission profile.
- Claims agents and Rules agents cannot communicate directly, call each other, inspect each other's memory, or modify each other's workspace.
- All cross-stage handoffs are immutable artifacts and typed messages routed by the Run Control Plane.
- The Run Control Plane is deterministic application logic, not an LLM. It owns run state, authorization, reviewer gates, artifact versions, and message ACLs.
- Children receive self-contained task briefs and bounded context. Writable child workspaces must not overlap.
- Agent/tool activity must be auditable. Do not display or log private model chain-of-thought.

### STAGE 1 REQUIREMENTS

1. Read the entire target report, not just the Section 16.3 excerpt. Preserve headings, paragraphs, tables, page/paragraph/table/cell locators, and relevant cross-references. Build a complete outline and identify the deepest Section 16.3 subsections. Do not silently use the first heading if Section 16.3 is missing or ambiguous; flag for reviewer confirmation.
2. Profile every uploaded source file and worksheet/table with complete record counts. Use streaming/chunked ingestion and tools; do not send the full dataset to the model or rely on 100-row previews.
3. Discover candidate keys, join cardinality, duplicate expansion, unmatched keys, field types, null/distinct stats, date ranges, and explicit export filter metadata.
4. Generate `source_knowledge.md` for the reviewer and canonical JSON artifacts for agents. Distinguish observed, inferred, and unknown filters. Never invent source filters.
5. Extract one independent claim per reported number/assertion at the lowest meaningful subsection. Preserve exact source text and locator. Model entity/unit, numerator, denominator, time period, population, subgroup, and claim type explicitly.
6. Do not create redundant independent claims for simple derived percentages. Store a derived value linked to parent claims only when same scope/population/period/unit are demonstrably equivalent. If uncertain, preserve and flag.
7. Create exactly one concise evidence hint per claim. The hint is an investigation guide, not validated proof or a final rule.
8. Use typed Strands tools for claim registry operations: add, update, split, merge, soft-delete, derive/link, list/get, validate. Persist every change with stable ID, version, optimistic concurrency, and history.
9. Produce a frozen Stage 1 bundle and wait for authenticated reviewer approval.

### STAGE 2 REQUIREMENTS

1. Start only with a frozen approved Stage 1 artifact hash/version.
2. Work claim-by-claim. Use autonomous investigation; do not assume the claim hint is ground truth.
3. Provide tools for file navigation, source inspection, full-data querying, join tests, Python file write/edit/read/delete, diff, execution, tests, logs, and artifact inspection.
4. Let the model decide the next tool call. The orchestrator may create a plan, but do not hardcode a fixed set of filters or fields for all claims.
5. Generate per-claim `plan.md`, `evidence_bundle.json`, `rule_spec.json`, `analysis.py`, tests, pinned dependencies, execution log/result, provenance, tool history, and artifact manifest.
6. Record filters and their provenance, counts before/after filters, entity key, distinct/count semantics, join cardinality, numerator/denominator, date bounds, and exact source coordinates.
7. Use a real isolated sandbox. Read-only input, writable claim workspace, non-root, network restrictions, resource limits, pinned image and dependencies, no host credentials. Fail closed if the sandbox is unavailable. Never execute generated code on the web host as fallback.
8. Support inspect-error-edit-retry loops and scoped subagents. Set finite tool-call/runtime/token/cost/repair limits, detect repeated tool-call loops, preserve every attempt, and record why the code changed.
9. Never modify original source files or the approved Stage 1 bundle.
10. Do not change filters solely to match the PBRER number. Report discrepancies honestly.
11. Produce a frozen Stage 2 artifact manifest and wait for reviewer approval.

### STAGE 3 REQUIREMENTS

1. Start in a fresh independent Strands session, with read-only access to approved Stage 1, Stage 2 artifacts, and immutable sources.
2. Do not trust Rules agent self-report. Inspect code and rule specifications. Re-run the actual code or reconstruct the calculation independently in a separate sandbox.
3. Validate target claim linkage, locator, entity/unit, source selection, filters, dates, population, join cardinality, duplicate effects, numerator/denominator, execution reproducibility, tests, source hashes, and row/cell provenance.
4. Return per-claim status `PASS`, `DISCREPANCY`, `FAIL`, `INCONCLUSIVE`, `NEEDS_HUMAN_REVIEW`, or `UNRESOLVED`, with individual checks and evidence.
5. A result mismatch is not automatically a rule failure. Classify whether the report, source coverage, population, entity definition, or rule is in error/ambiguous.
6. If rework is needed, send a typed request to the Run Control Plane. The control plane may reopen Stage 2 (or Stage 1 if the claim is wrong). Do not directly message the Claims or Rules agent.
7. Stage 3 produces `evaluation_report.json` and per-claim evaluation artifacts. A human must approve the final report.

### AWS / MODEL REQUIREMENTS

- Use AWS Bedrock Claude via the Strands Bedrock model integration supported by the currently installed SDK version.
- Use least-privilege ECS task roles; do not expose AWS credentials to models or generated code.
- Use private S3 + KMS for uploads/artifacts, durable relational storage for run/claim/approval/audit state, and Step Functions Standard or an equivalent durable workflow for human gates.
- Keep local development possible through a local state store and mocked Bedrock responses, but production sandbox execution must fail closed.
- Do not introduce a graph database unless profiling/query requirements justify it; JSON knowledge graph plus relational metadata is an acceptable first implementation.

### UI REQUIREMENTS

Preserve the existing upload and three-column report workspace where practical. Right panel is a Claim Register grouped by leaf subsection. Each claim expands to show Stage 1 hint, Stage 2 evidence/rule/code/results/provenance, and Stage 3 evaluation. Show three stage orchestrators and subagents through activity events. Add explicit Start/Approve/Request changes buttons. Only the reviewer click initializes the next stage. Display tool activity and artifacts, not chain-of-thought.

### IMPLEMENTATION METHOD

1. First produce a repository map and identify what is safe to preserve vs replace. Do not start coding until the stage contracts and run-state transition tests are designed.
2. Implement the Run Control Plane, persistence contracts, and upload boundary first.
3. Implement the Strands agent factory, scoped tool permissions, and durable event model.
4. Implement Stage 1 end-to-end and its reviewer gate before adding Stage 2.
5. Implement Stage 2 sandbox/code loop and reviewer gate before adding Stage 3.
6. Implement Stage 3 independent evaluation and targeted rework routing.
7. Finish with integration tests, synthetic fixtures, security tests, and end-to-end reviewer-gate tests.

At each step, report exact files changed, tests run, artifacts produced, known gaps, and whether the implementation meets its exit criteria. Do not claim a stage is complete because the agent wrote a file or marked a status string; verify the persisted artifacts and gate invariants.

### DEFINITION OF DONE

A run can be uploaded, Stage 1 started by a reviewer, claims reviewed/edited/approved, Stage 2 started only from the approved claim hash, scripts generated/executed/repaired in isolation, artifacts reviewed/approved, Stage 3 independently rerun and evaluated, discrepancies routed through the Control Plane, and final reviewer sign-off persisted. Every claim's path from target text -> hint -> source evidence -> rule/code -> execution -> independent validation is reproducible and auditable. Claims and Rules agents cannot directly communicate or bypass stage gates.

---

## 18. Reference material

### TraceWise repository inspected

- Repository: https://github.com/Visy6git/TraceWise
- Reviewed commit: https://github.com/Visy6git/TraceWise/commit/15ebf04cc0ccd41b7b828b5e25444ded6eaf1cc8
- Key current paths: `app/main.py`, `app/agents/*`, `app/agent_tools/source_tools.py`, `app/schemas/*`, `app/services/execution_engine.py`, `app/services/sandbox.py`, `app/services/bedrock.py`, `app/services/ag_ui.py`, `tests/test_agent_architecture.py`, and `static/*`.

### Crush harness principles inspected

- Repository: https://github.com/charmbracelet/crush
- Reviewed commit: https://github.com/charmbracelet/crush/commit/8f1f02951cabc30b82e497fd916ca434bad1e6f4
- Relevant implementation areas: `internal/agent/agent_dispatch.go`, `internal/agent/templates/agent_dispatch_tool.md`, `internal/agent/templates/agent_tool.md`, `internal/agent/tools/edit.go`, `internal/agent/tools/write.go`, `internal/agent/tools/bash.go`, `internal/backend/permission.go`, and `internal/agent/loop_detection.go`.
- Principles borrowed: separate child context, self-contained task briefs, explicit read/write access, tool-level permissions, edit history/diffs, reliable session lifecycle, bounded subagent work, and repeated-tool-loop detection. TraceWise should not copy Crush's entire TUI or provide untrusted shell access to source data.

### Strands Agents

- Multi-agent patterns: https://strandsagents.com/docs/user-guide/sdk/multi-agent/multi-agent-patterns/
- Graph: https://strandsagents.com/docs/user-guide/sdk/multi-agent/graph/
- Agents-as-Tools: https://strandsagents.com/docs/user-guide/sdk/multi-agent/agents-as-tools/
- Agent-to-Agent: https://strandsagents.com/docs/user-guide/sdk/multi-agent/agent-to-agent/
- Session management: https://strandsagents.com/docs/user-guide/sdk/agents/session-management/
- Custom tools: https://strandsagents.com/docs/user-guide/sdk/tools/custom-tools/

### AWS

- Bedrock tool use: https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html
- Bedrock client-side tool use: https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-client-side.html
- Step Functions callback task token: https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html
- ECS task IAM roles: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/security-iam-roles.html
- ECS task definition parameters: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html

---

## Final recommendation

Build the Run Control Plane and Stage 1 first. The critical success criterion is that the Claims Orchestrator can read the complete report and source set, create a correct leaf-level Claim Register with clear provenance, and pause for review. Then build the Rules Orchestrator as a genuine coding harness with an isolated workspace and a full tool loop. Only after those two outputs are durable and reviewable should the independent Evaluator be introduced.

This is the shortest path to a genuinely autonomous system without recreating the current failure mode: several agent classes that appear to collaborate, but are actually coupled heuristics sharing incomplete previews and writing optimistic status fields.
