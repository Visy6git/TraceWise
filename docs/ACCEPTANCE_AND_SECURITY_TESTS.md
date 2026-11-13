# Acceptance and security test plan

This plan is intentionally broader than the starter test suite. The listed overlay tests cover only contract/profile/fail-closed/package basics. Add the integration suites below in the repository after applying the overlay.

## Stage 3 authoring

1. Start rejected unless run state is `RULES_APPROVED` and submitted hash exactly equals current Stage 2 manifest.
2. Start request is idempotent; duplicate idempotency key does not launch another harness.
3. Fresh workspace per attempt; a retry cannot inherit prior mutable files/session memory.
4. Sanitized Stage 1/2 artifact copy excludes claim data rows, source excerpts containing direct identifiers, tool transcripts, secrets and credentials.
5. Stage 1/2 directory hashes before/after authoring are identical.
6. Harness output missing required package artifacts results in `needs_review`/blocked, never an approved blueprint.
7. `reproduction_tested=true` requires an authenticated isolated test result bound to the script hash, fixture hash, environment image and blueprint hash.
8. Agent cannot set approval status; human approval must bind exact Stage 3 manifest hash/version.
9. Rework retains old artifact and blueprint versions and emits dependency/audit changes.
10. Invalid Section 16.3 locators, duplicate claim IDs, unknown dataset refs, unknown policy refs and missing required fields fail validation.

## Source compatibility

1. New source filename and renamed worksheet with exact logical field headers can map without using filename as authority.
2. An alias or semantic mapping is a reviewer-required warning.
3. A missing required field blocks generation.
4. Two equally plausible sheets block generation as ambiguous.
5. A physical field type change (date to free text, numeric to categorical) blocks or requires review.
6. Key uniqueness/cardinality change is detected and does not silently fan out rows.
7. Missing join partners, additional duplicate versions and duplicate expansion are surfaced.
8. Initial/follow-up/version selection and as-of cutoff are tested at interval boundaries.
9. A latest timestamp cannot override the approved version policy.
10. Hidden sheets, formulas, merged cells and unusual preambles are either supported with explicit tests or reported as known limitations.

## Generation execution

1. Generation requires approved blueprint version/hash, immutable source manifest and period/as-of context.
2. It cannot read the old target DOCX or old learning workspace.
3. It cannot mutate approved blueprint object or original source object.
4. Production configuration with no isolated worker blocks before starting execution.
5. A configured `local-development` executor is allowed only with `TRACEWISE_ENV=development` and explicit opt-in, and CI fixtures are synthetic.
6. The isolated worker receives only generation-scoped read-only input, one writable output mount, pinned environment/image and constrained resource/time limits.
7. It has no network egress and no ambient secrets/credentials.
8. Output file list is allow-listed; path traversal, symlink, unexpected file, oversized output or mismatched hashes are rejected.
9. DOCX output contains expected section heading order/table layout and every value has provenance.
10. Missing/ambiguous values are shown as exceptions; they are not fabricated or suppressed.

## Tenant/privacy

1. Every route verifies principal tenant ownership for blueprints, generations, source objects, artifacts and events.
2. Caller-supplied tenant IDs cannot access a different tenant.
3. File upload rejects unsupported magic bytes even when extension is valid.
4. Event payloads redact patient identifiers, raw records, prompts and credentials.
5. Tool output previews are bounded and redacted before both UI publication and tool-history persistence.
6. Artifact downloads require authorization and verify artifact belongs to the requested generation/tenant.
7. Path traversal and symlink escape tests fail closed.

## UI / AG-UI

1. Learning/Generator mode tabs can be switched without corrupting either active run.
2. Generator is locked until an approved blueprint is available to the authenticated tenant.
3. Learning and generation histories display separate IDs and data models.
4. Stage3 starts only after server acknowledgement and current Rules approval.
5. Artifact changes and reviewer decisions refresh the panel.
6. Generation compatibility blockers prevent calculation and show proposed mappings as proposals only.
7. SSE reconnect/resume uses event cursor and does not duplicate state transitions.
8. Narrow viewport layout remains usable and controls remain keyboard-accessible.
9. Loading, empty, error, blocked, review and completed states have visible feedback.

## Baseline regression

- Run all current Stage 1/2 tests unmodified before and after integration.
- Compare Stage 1 claim count/artifact manifest outputs on a de-identified synthetic fixture.
- Compare Stage 2 claim-level artifact bundle and generated script outputs on the same fixture.
- Confirm existing upload, run History, claim edit, reviewer gate, artifact viewer, source drawer and AG-UI replay still function.
