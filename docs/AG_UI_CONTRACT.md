# AG-UI 1.0 contract for TraceWise

TraceWise uses the Agent-User Interaction Protocol as the transport contract between agent runtime and the workbench. The protocol's JSON Schema is authoritative. This starter includes the event subset the UI actively projects; the backend must validate every emitted event against the selected AG-UI 1.0 schema before production.

Upstream references:
- Spec: https://github.com/ag-ui-protocol/ag-ui/tree/main/docs/spec/1.0
- Basic event model: https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/spec/1.0/basic/index.mdx
- JSON Schema: https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/spec/1.0/schema.json

## Transport

- `GET /api/runs/{run_id}/events?cursor=<opaque-cursor>` streams AG-UI event objects as Server-Sent Events.
- Each SSE frame uses a JSON `data:` line, with optional SSE `id:` used as a durable replay cursor.
- The API authenticates/authorizes the run before opening the stream.
- The production implementation first replays durable events after the cursor, then tails the event broker; reconnection must not silently lose events.
- `RUN_STARTED` and `RUN_FINISHED` / `RUN_ERROR` bound a run lifecycle. Stage transitions are operational steps, not implicit pipeline transitions.
- Do not emit `REASONING_*` as a UI activity feed. TraceWise deliberately exposes concise operational summaries and tool calls, not private internal model reasoning.

## Standard events the UI understands

| Event | TraceWise projection |
|---|---|
| `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR` | Run connection/lifecycle/error state |
| `STEP_STARTED`, `STEP_FINISHED` | Stage/subtask progress |
| `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END`, `TOOL_CALL_RESULT` | Tool activity, tool name, bounded safe arguments/result summary |
| `STATE_SNAPSHOT`, `STATE_DELTA` | UI state synchronization; production client should apply JSON Patch deltas safely |
| `ACTIVITY_SNAPSHOT`, `ACTIVITY_DELTA` | Activity timeline synchronization |
| `SUBAGENT_STARTED`, `SUBAGENT_FINISHED`, `SUBAGENT_ERROR` | Subagent cards, counts, state and bounded completion reports |

## TraceWise CUSTOM event namespace

Use AG-UI `CUSTOM` for application-specific UI data. `name` is namespaced; `value` is a typed JSON object. Never put raw patient-level source rows, credentials, sandbox task tokens or private reasoning in it.

| `name` | Example `value` fields | Purpose |
|---|---|---|
| `tracewise.stage` | `stage`, `status`, `progress`, `attemptId`, `manifestVersion` | Stage status and progress |
| `tracewise.activity` | `stage`, `title`, `detail`, `kind`, `agent`, `source`, `artifact`, `status` | Compact timeline event |
| `tracewise.artifact` | `artifactId`, `logicalPath`, `version`, `sha256`, `claimId`, `status` | Artifact tray update |
| `tracewise.claim` | `claimId`, `claimVersion`, `sectionId`, `status`, `changedFields` | Claim Registry update without dumping PHI |
| `tracewise.agent` | `agentId`, `parentAgentId`, `stage`, `name`, `status`, `taskSummary` | Agent/subagent inventory |
| `tracewise.review` | `stage`, `gateStatus`, `manifestHash`, `decisionRequired` | Explicit human review gate |

## Event projection rules

1. The Run Control Plane persists event envelopes before publishing them.
2. Every event carries `runId`/`threadId` as required by the upstream AG-UI schema; stage/claim/agent metadata is added only where the schema permits it.
3. `TOOL_CALL_ARGS` and `TOOL_CALL_RESULT` are redacted and bounded. They are summaries, not complete source payloads.
4. Tool names should be user-readable (`profile_column`, `test_join_cardinality`, `write_file`, `run_python`, `run_pytest`, `publish_artifact`).
5. A subagent event identifies the subagent invocation, not its full hidden conversation.
6. On reconnect, the backend may send a snapshot then deltas, or replay durable events from the supplied cursor. The client must tolerate both patterns without duplicate visible rows.
7. The browser cannot approve a stage through event input. Review actions remain authenticated HTTP operations bound to expected manifest version/hash.

## Current starter implementation

- `frontend/src/types/agui.ts` defines a focused typed subset.
- `frontend/src/lib/agui.ts` subscribes over `EventSource` and dispatches standard tool/subagent and TraceWise `CUSTOM` events.
- `app/services/event_stream.py` serializes JSON SSE frames and emits a placeholder `RUN_STARTED` + `tracewise.stage` event.
- `app/api/events.py` exposes the placeholder stream.

The stream is not yet durable, replayable or backed by a worker. It is not a claim that a live agent is running.
