# UI feature map

| UI area | Implemented interaction | Backend binding needed |
|---|---|---|
| Top run bar | Current run ID, demo indicator, settings/account affordances | Identity, run selector, user profile |
| Left document tree | Expand/collapse, section selection, Section 16.3 navigation | Extracted report hierarchy, selection corrections |
| Source inventory | Source drawer, file status, row/sheet counts, integrity display | Source manifest, profiles, hashes, usage graph |
| Intake modal | One target + multiple sources, extension validation, remove source, create demo run | Multipart upload, malware/size/type validation, immutable S3 objects |
| Stage rail | Current stage, progress, status, agent/artifact counts | Durable stage attempt snapshot + AG-UI state/activity events |
| Activity panel | Timeline, agent/tool/artifact/gate event styles, latest/all | Durable event log + AG-UI event broker |
| Document panel | Viewer layout, excerpt, table, claim locator navigation | Real DOCX/PDF renderer and exact block locators |
| Artifact explorer | Group by stage, type/status/version/size, open action | Artifact manifest and authorized download/preview endpoints |
| Claim Register | Search, status filter, claim select, reported value, unit, hint, epistemic markers | Claim Registry API and claim version event |
| Claim editor | Local edit and draft save activity | Optimistic concurrency PATCH; stage edit authorization; audit log |
| Lineage preview | Source chips open source drawer; target link selects report section | EvidenceBundle row/column/filter/join provenance graph |
| Agent view | Main and subagent cards, status, current task, elapsed, child count | AG-UI subagent events and durable agent activity projection |
| Stage controls | Local demo start, review, approve, request changes | Authenticated start/review/cancel APIs and manifest hash checks |
| Footer | Immutable input/version/event-mode cues | Source hash verification, artifact version, SSE connection state |

All sample data are illustrative. Local demo stage actions simulate state and artifact creation; they do not invoke Strands or produce real calculations.
