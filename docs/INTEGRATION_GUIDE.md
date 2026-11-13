# Integration guide — additive Stage 3 + Generator overlay

Baseline: `52885efad0971ea0c5af8c2287124181f2955040`. Re-check live `main` before applying.

## 1. Apply new files safely

From the current TraceWise repo root, run the included `APPLY_OVERLAY.sh` or PowerShell equivalent. It copies only absent paths. Review every skipped path manually.

## 2. Backend router registration

In `app/main.py`, add `from app.api import blueprints` and register:

```python
app.include_router(blueprints.router, prefix="/api")
```

Do not register twice. Confirm OpenAPI exposes `/api/blueprints`, `/api/generations`, and `/api/runs/{run_id}/stages/understanding/...`.

## 3. Replace the legacy Stage 3 placeholder

The baseline `app/api/stages.py` imports `run_evaluation_stage` and routes all `stage=evaluation` actions to the placeholder. The new API uses the same persisted `evaluation`/`EVALUATION_*` state slot for compatibility, but presents it as `understanding`.

Do not leave two independent start/review paths capable of racing state transitions. Recommended integration:

- Make the legacy `/stages/evaluation/start` endpoint return a `307`/`409` with a deprecation message pointing to `/stages/understanding/start`, OR delegate to the new handler with the exact same state/hash validator.
- Remove the placeholder import from `_STAGE_RUNNERS` for evaluation; the normal Stage 1/2 runner table should remain intact.
- Preserve internal run-state values until an explicit migration is designed. The UI's third stage label and events should be `Section 16.3 Understanding` / `understanding`.
- Do not allow `StageName.evaluation` to invoke the old placeholder after the new route is active.

## 4. Stage 3 panel integration in `frontend/src/App.tsx`

Add imports:

```tsx
import { WorkspaceModeTabs, type WorkspaceMode } from './components/WorkspaceModeTabs';
import { Stage3BlueprintPanel } from './components/Stage3BlueprintPanel';
import { SectionGeneratorWorkspace } from './components/SectionGeneratorWorkspace';
import { generatorApi } from './lib/generatorApi';
import './styles/generator.css';
```

Add state near the other top-level component state:

```tsx
const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('learning');
const [approvedBlueprintAvailable, setApprovedBlueprintAvailable] = useState(false);
```

When API mode is active, load approved blueprints (tenant identity must come from authenticated backend context, not arbitrary query parameters):

```tsx
useEffect(() => {
  if (!apiMode) return;
  let cancelled = false;
  const refresh = () => generatorApi.listBlueprints()
    .then(items => { if (!cancelled) setApprovedBlueprintAvailable(items.length > 0); })
    .catch(() => { if (!cancelled) setApprovedBlueprintAvailable(false); });
  void refresh();
  const timer = window.setInterval(refresh, 10000);
  return () => { cancelled = true; window.clearInterval(timer); };
}, [apiMode]);
```

At the app shell's top-level return, render the tabs above the current Learning Workbench body:

```tsx
<WorkspaceModeTabs
  mode={workspaceMode}
  onChange={setWorkspaceMode}
  generatorEnabled={approvedBlueprintAvailable}
/>
{workspaceMode === 'generator'
  ? <SectionGeneratorWorkspace />
  : <ExistingLearningWorkbench />}
```

`ExistingLearningWorkbench` above is a conceptual wrapper: do not create a second copy of the app. Move the existing returned Learning Workbench JSX into a fragment/child component or wrap it in `{workspaceMode === 'learning' && (...)}` while preserving hooks at the top-level component. Do not conditionally call hooks. Preserve the current `run`, `selectedClaim`, History tab and state while the Generator component is mounted/unmounted. Consider lifting Generator selected generation ID into app-level state or persistent URL state if it must survive mode switches.

In API mode, the Generator tab unlocks when at least one approved blueprint exists. In demo mode, keep it locked unless a clearly labelled mock blueprint fixture is intentionally enabled. Do not unlock based only on local `stageStatus`.

## 5. Mount the Stage 3 panel

The existing right/center Learning Workbench render has the Stage controls and activity/artifact tabs. Mount `Stage3BlueprintPanel` in the Stage controls or artifact-review area when:

- Stage 2 has completed and run state is `RULES_APPROVED`, `EVALUATION_RUNNING` or `EVALUATION_AWAITING_REVIEW`;
- a Learning Run ID is present.

Props:

```tsx
<Stage3BlueprintPanel
  runId={run.runId}
  stage2ManifestHash={run.stageManifestHashes?.rules}
  stageStatus={mapLegacyEvaluationStatusToUnderstanding(run.status)}
  stage3ManifestHash={run.stageManifestHashes?.evaluation}
  onUpdated={() => run.runId && void refreshLiveRun(run.runId)}
/>
```

Implement `mapLegacyEvaluationStatusToUnderstanding` as a pure mapper, not a persisted state rename. It should translate:
- `RULES_APPROVED` -> `ready`
- `EVALUATION_RUNNING` -> `running`
- `EVALUATION_AWAITING_REVIEW` -> `review`
- `FAILED` with `active_stage === 'evaluation'` -> `error`
- approved/completed final state -> `approved`

Do not show a Stage 3 start button unless the Rules manifest hash exists and the server confirms Rules is approved. The component API call is the authority.

## 6. Rename visible third-stage copy

Replace visible UI text:
- `Stage 3 evaluation` -> `Section 16.3 Understanding`
- `Independent evaluation` -> `Reproduction blueprint`
- `Stage 3 is a placeholder` -> remove

Keep legacy database field names and `StageName.evaluation` until migration is deliberately planned. API/events should expose a display alias `understanding` without breaking existing run snapshots.

## 7. Generator run events

`SectionGeneratorWorkspace` subscribes using the generation ID as the event key. Verify `GET /api/runs/{run_id}/events` only assumes a generic broker key and does not require a `runs` table lookup. If it does require a learning run, add an authenticated `GET /api/generations/{generation_id}/events` endpoint that streams the same `EventBroker` for the generation ID.

The component's current periodic refresh must be changed to prevent overlapping requests and stale state updates. Prefer a generation detail endpoint plus SSE as primary state source and one explicit refresh button; use a single timer with cleanup if polling remains.

## 8. Required API security changes before production

The overlay is not production-ready until the following are implemented:

- Authenticate all blueprint/generation endpoints.
- Derive tenant ID from the server-side principal. Remove caller-controlled tenant form/query parameters except in isolated developer fixtures.
- Store uploads under the same tenant namespace recorded by the generation row.
- Check tenant ownership on blueprint list/get, generation list/get, artifact downloads and event subscriptions.
- Replace `human_reviewer_1` with authenticated reviewer ID + role/permission check.
- Make reviewer approval transactionally bind Learning Run status, exact Stage3 manifest hash and blueprint record status.
- Persist idempotency keys and prevent duplicate starts/duplicate Generation Run creation.
- Validate file magic bytes, not just extensions. Add malware scanning and per-run total upload quota.

## 9. Current SQLite vs production DB

`BlueprintRepository` adds SQLite DDL to the existing DB adapter for local development. Move these tables into the production migration system (Aurora PostgreSQL/RDS) and use transactions/CAS versions. Do not assume SQLite's `INSERT OR REPLACE` behavior is suitable for production immutable history.

## 10. Run local validation

```bash
python -m compileall -q app
pytest -q
cd frontend && npm run typecheck && npm run build
```

Run the Stage3 overlay tests after applying files:

```bash
pytest -q tests/test_blueprint_contract.py tests/test_source_compatibility.py tests/test_execution_boundary.py tests/test_blueprint_package.py
```

Also add tests proving existing Stage 1/2 API and UI behavior did not regress. A passing overlay test subset is not evidence of a complete production-ready system.
