# Implementation handoff — replace the placeholders in this order

This is the operating brief for the next coding agent. The goal is to turn the starter into the real autonomous harness while preserving the UI contract and the separation between the three stages.

## First: validate the live repository and security posture

1. Inspect the actual target repository HEAD and working tree before porting files. Do not assume the earlier review commit is still current.
2. Re-check whether the repository is public and inspect reachable Git history, releases, Actions artifacts, branches and forks for previously committed PBRER/CSMR runtime data. If sensitive workbooks were ever pushed, follow the repository owner's incident process; deleting the current-tree files is insufficient.
3. Confirm tenant model, identity provider, data residency, retention and approved Bedrock model/inference profile.
4. Keep real uploads, logs, generated scripts and outputs out of Git.

## Milestone 0 — make the starter deterministic

- Create a package lock file for frontend dependencies and pin production image/dependency versions.
- Configure linting, formatting, typecheck, API schema generation and CI.
- Validate all Pydantic schemas and API response envelopes.
- Replace demo fixtures with an explicit sample tenant/run fixture only in local development; do not ship sample data into a production tenant.

## Milestone 1 — durable Run Control Plane

Implement PostgreSQL tables/migrations for tenants, users/roles, runs, source_objects, source_sets, stage_attempts, approvals, claims, claim_versions, artifacts, artifact_dependencies, tasks, tool_events, agent_sessions and audit_events.

Requirements:
- Compare-and-swap `version` column on run/claim/approval operations.
- Idempotency keys for run creation, stage start and review submission.
- Append-only audit/change history.
- A stage transition validator backed by a database transaction.
- Approval must compare exact manifest hash + version and reviewer role.
- Start Rules only from the state reached after Stage 1 approval. Start Evaluator only after Stage 2 approval. No automatic advance.
- Rework creates a new attempt/artifact version and reopens only the affected stage through an explicit control-plane transition.
- Dependency invalidation supersedes descendants but never deletes prior evidence.

Wire the existing `app/control_plane` modules to the repository and add migration-backed tests.

## Milestone 2 — secure file intake and document/source intelligence

- Implement streaming upload endpoints and S3 object storage with content hashes, MIME/magic-byte checks, malware scanning, size limits and tenant ACLs.
- Keep immutable originals in private S3; derive extracted text/rows into run-scoped analytical storage.
- Build canonical DOCX/PDF document blocks with stable paragraph/table/page/cell locators, full outline and section detection warnings.
- Profile every source file and every worksheet/table including hidden sheets where available. Handle preambles/header rows, formulas, merged cells, date formats and extraction warnings.
- Use streaming/chunked ingestion. The LLM only receives bounded profiles, summaries and selected slices.
- Build `source_knowledge.md`, `source_knowledge.json`, `knowledge_graph.json`, schema profiles, relationship tests and observed/inferred/unknown filter notes.
- Ensure every evidence statement carries a source pointer or explicit inference label.

## Milestone 3 — Strands Stage 1 Claims Orchestrator

- Use AWS Bedrock Claude via Strands `Agent` / Bedrock model adapter; do not reimplement the loop as a custom boto3 Converse agent framework.
- Build dedicated Strands tools for outline, target blocks, source profiles and Claim Registry operations.
- Use Agents-as-Tools for constrained source/document/claim specialists. Give each specialist a standalone task prompt and explicit context/output schema.
- Atomize one independent assertion per claim at the deepest meaningful Section 16.3 leaf subsection. Preserve raw text + exact locator.
- Require quantitative entity/unit semantics. Keep case/event/patient/subject/report/person-time units distinct.
- Attach exactly one concise Stage 1 Evidence Hint to every claim, with observed/inferred/unknown information and source refs.
- Link a percentage as derived only when all scope dimensions are equivalent; otherwise retain a separate claim or flag a reviewer decision.
- Validate all leaf subsections have an explicit claims/no-claims outcome.
- Publish frozen artifacts and move to `CLAIMS_AWAITING_REVIEW` only. Do not start Stage 2.

## Milestone 4 — Strands Stage 2 Rules coding harness

For each approved claim create an isolated logical workspace and the following required artifacts:

```text
plan.md
evidence_bundle.json
rule_spec.json
analysis.py
tests/test_analysis.py
requirements.lock
execution.json
result.json
provenance.json
tool_history.jsonl
stdout.log
stderr.log
artifact_manifest.json
```

Build a Crush-inspired tool surface with `read_file`, `write_file`, exact-match `edit_file`, `multi_edit`, `delete_workspace_file`, `diff_file`, `read_file_version`, search/glob, source schemas/profiles/samples, join-cardinality tests, structured read-only query, run Python/pytest, inspect job output/artifacts and artifact publish. All paths remain workspace-relative and scoped. Require read-before-write and version/hash preconditions.

- Give specialist subagents independent sessions and non-overlapping workspaces; default them to read-only.
- Keep per-claim tool/turn/cost/runtime/repair budgets; detect repeated tool-call signatures and repeated errors.
- Start with one initial execution and no more than two automatic repair cycles (configurable).
- Preserve failed attempts/logs. Do not tune filters to force target equality.
- Original data and approved Stage 1 claims remain read-only.
- Stage 2 becomes reviewable only when every approved claim has a reproducible artifact bundle or explicit NOT_COMPUTABLE / NEEDS_HUMAN_INPUT / UNRESOLVED outcome.

## Milestone 5 — independent Evaluator

- Use a new Strands session, role and workspace, with read-only Stage 1/Stage 2/source capabilities.
- Independently run the published script in a clean environment with pinned dependencies and a fresh sandbox. Do not trust the Rules `result.json` as proof.
- Verify target locator, claim linkage, entity/unit, source coverage, period, population, filter provenance, join/cardinality, deduplication, numerator/denominator, exact source lineage, hashes and original-source immutability.
- Classify outcomes using `PASS`, `DISCREPANCY`, `FAIL`, `INCONCLUSIVE`, `NEEDS_HUMAN_REVIEW` or `UNRESOLVED`.
- Numeric mismatch is not itself a code failure. Diagnose report/source/scope/definition/logic differences without target fitting.
- Route rework through the Run Control Plane; never message Claims or Rules directly.
- Require final human sign-off after evaluator completion.

## Milestone 6 — AG-UI live execution trace

Preserve the current `frontend/src` state model, replace local demo actions with authenticated API calls, and connect the production event broker to `GET /api/runs/{run_id}/events`.

Emit AG-UI lifecycle, step, tool, state/activity and subagent events, plus the TraceWise `CUSTOM` telemetry described in `AG_UI_CONTRACT.md`. Persist before publish. Support snapshots/replay/reconnect. Redact arguments/results and do not stream chain-of-thought, raw row data or secrets.

The UI should continue to show:
- current stage, attempt, state and progress;
- each agent and subagent, parent-child relation, current safe task summary and count;
- every source document/sheet the stage actually inspected;
- every artifact as it is written/versioned, plus hash/status;
- tool lifecycle and bounded safe output summaries;
- each stage's explicit review gate and approval state;
- claim-level lineage from target locator to source rows/joins/filters/code/result/evaluation.

## Milestone 7 — AWS production hardening

- Deploy UI/API to ECS Fargate behind ALB/API Gateway; OIDC/Cognito auth.
- Use Step Functions Standard with callback task tokens for human review waits.
- Use separate Fargate task definitions and IAM roles for Claims, Rules, Evaluator and sandbox execution.
- Use S3 versioning + SSE-KMS + Block Public Access, RDS/Aurora PostgreSQL, SQS as useful, CloudWatch and OTel/X-Ray.
- Use private VPC subnets and no public IP for agents/sandbox. Limit outbound egress.
- Keep Bedrock and S3 access behind narrowly scoped task roles; no static credentials.
- Enforce backup/retention, access review, incident response, deletion and tenant isolation.

## Definition of done

- A reviewer cannot start Stage 2 until Stage 1 artifact versions are approved and frozen.
- A reviewer cannot start Stage 3 until Stage 2 manifest is approved and frozen.
- Claims and Rules have no direct communication/session/workspace access.
- Every claim has a locator + one evidence hint; every Rules claim has a complete artifact bundle or explicit unresolved disposition.
- Evaluator independently reruns actual artifacts in a separate sandbox and records a precise status.
- Source hashes remain unchanged after all runs.
- No generated code runs on the API host, including local fallback behavior.
- AG-UI reconnect/replay does not lose or duplicate material events.
- Full E2E, permissions, stale approval, loop-budget, sandbox escape, source immutability and PHI-redaction tests pass.

## Avoid these shortcuts

- Do not rename the current monolithic agent and call it three orchestrators.
- Do not use regex-only claim extraction as the complete Claims system.
- Do not select the first keyword-matched spreadsheet as evidence.
- Do not make a hardcoded metric-template generator the Rules agent.
- Do not let Evaluator reuse Rules memory or trust its self-attested result.
- Do not treat a local queue as network A2A. Add A2A transport only if an agent becomes a real separate service.
- Do not deploy the placeholder API as a working PV calculation system.
