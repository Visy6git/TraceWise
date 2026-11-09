# Security, privacy and execution policy

## Sensitive-data boundary

- Treat all PBRER source workbooks, case listings, patient-level extracts, generated code, logs and artifacts as confidential.
- Keep runtime data outside Git and outside public CI logs. `.gitignore` is defense-in-depth, not a data governance control.
- Use private S3 with versioning, SSE-KMS, Block Public Access, restrictive tenant/run prefixes and audited access.
- Pseudonymize identifiers before model context where practical; preserve direct identifiers and exact source mapping only in the protected analytical layer.
- Redact identifiers, secrets, task tokens, connection strings and raw source rows from telemetry, stdout/stderr, tool results and generated Markdown.
- Define retention, deletion, legal hold, backup and access review policies before production use.

## Agent tool permissions

- Tools use Pydantic input models, run/tenant/role scoping, strict output limits, audit events, correlation IDs, timeouts and explicit error types.
- Never expose arbitrary absolute paths, unrestricted shell, raw SQL/WHERE clauses or generic filesystem APIs to an agent.
- Read-only is default. Stage 2 write access is limited to one claim workspace. Parallel writable subagents must have disjoint scopes.
- Evaluator tools are read-only and use separate credentials/sandbox.
- Claims cannot inspect Rules sessions or workspaces. Rules cannot inspect Claims live context. Cross-stage artifact references are mediated by the Run Control Plane.

## Generated-code sandbox

Generated Python is untrusted code. Production policy:

- One isolated execution container/task per claim attempt or suitably isolated batch.
- Non-root user; read-only root filesystem; dropped capabilities; no-new-privileges.
- No general network egress; `--network none` for local Docker execution.
- Original source snapshot mounted read-only; only the specific claim workspace writable.
- CPU, memory, PID, wall-time, output-size, file-size and disk quotas.
- Pinned image digest and locked Python dependencies.
- No inherited developer credentials or broad AWS role; task role is narrowly scoped to artifact I/O when unavoidable.
- Container/task termination, cleanup and source checksum verification after execution.
- If the isolation backend is unavailable, fail closed. Do not run generated code in FastAPI or the agent host process.

The included `SandboxClient` raises `SandboxUnavailable` when `SANDBOX_REQUIRED=true` and no backend is configured. It has no unsafe host Python fallback.

## AWS deployment model

| Layer | Preferred service |
|---|---|
| UI/API | FastAPI on ECS Fargate behind ALB/API Gateway; Cognito or enterprise OIDC |
| Orchestration gates | Step Functions Standard with callback task token for reviewer pauses |
| Agent workers | Separate ECS Fargate tasks/roles for Claims, Rules and Evaluator |
| Queues | SQS for dispatch/retry where needed |
| Input/artifact storage | Private versioned S3, SSE-KMS |
| State/audit | RDS/Aurora PostgreSQL |
| Analytical data | Per-run DuckDB/Parquet or controlled query engine |
| Model | Bedrock Claude through Strands Agents |
| Observability | CloudWatch structured logs/metrics and OpenTelemetry/X-Ray |

Task tokens are secrets and must never reach the browser or an LLM. Review callbacks authorize a reviewer first, compare the expected manifest hash/version, then call `SendTaskSuccess` or `SendTaskFailure` server-side.
