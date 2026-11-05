from pathlib import Path
from uuid import uuid4
import hashlib
import json
import os
import shutil
import threading
import time
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .services.extractors import extract_file
from .services.event_metrics import EventMetricRule, calculate_case_event_metric
from .services.bedrock import is_bedrock_available, converse_sonnet, DEFAULT_SONNET_MODEL_ID
from .services.sandbox import AgentSandbox
from .services.ag_ui import ag_ui_manager, AGUIEvent
from .services.agents import MultiAgentOrchestrator, SectionMapping
from .services.sample_pbrer import generate_pbrer_sample_bundle

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'runtime'
RUNTIME.mkdir(exist_ok=True)

RUNS: dict[str, dict[str, Any]] = {}
ORCHESTRATORS: dict[str, MultiAgentOrchestrator] = {}
ALLOWED = {'.pdf', '.docx', '.xlsx', '.xls', '.csv'}

app = FastAPI(title='Tracewise · PBRER Document Intelligence POC', version='0.2.0')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')


@app.get('/', response_class=HTMLResponse)
def home():
    return (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')


@app.get('/api/health')
def health():
    bedrock_ok, bedrock_msg = is_bedrock_available()
    return {
        'status': 'ok',
        'bedrock_configured': bedrock_ok,
        'bedrock_model_id': os.getenv('BEDROCK_MODEL_ID', DEFAULT_SONNET_MODEL_ID),
        'bedrock_enabled': os.getenv('BEDROCK_ENABLED', 'false').lower() == 'true',
        'bedrock_message': bedrock_msg,
    }


def build_outline(profile: dict[str, Any]) -> list[dict[str, Any]]:
    outline = []
    for p in profile.get('paragraphs', []):
        text = p['text'].strip()
        import re
        if re.match(r'^\d+(\.\d+)?\s+\S', text) or (len(text) < 120 and any(kw in text.lower() for kw in ['section', 'periodic', 'exposure', 'reactions', 'signals', 'rsi', 'benefit'])):
            outline.append({'id': f"sec-{len(outline)+1}", 'title': text, 'source': f"Paragraph {p['paragraph']}"})
        elif len(text) < 180 and text.isupper() and len(text) > 4:
            outline.append({'id': f"sec-{len(outline)+1}", 'title': text, 'source': f"Heading {p['paragraph']}"})

    for page in profile.get('pages', []):
        import re
        for line in page['text'].splitlines():
            line = line.strip()
            if re.match(r'^\d+(\.\d+){0,4}\s+\S', line):
                outline.append({'id': f"pdf{page['page']}-{len(outline)+1}", 'title': line[:160], 'source': f"Page {page['page']}"})

    if not outline:
        outline = [
            {'id': 'sec-1', 'title': '1. Introduction', 'source': 'Report Structure'},
            {'id': 'sec-2', 'title': '2. Worldwide Marketing Approval Status', 'source': 'Report Structure'},
            {'id': 'sec-5.1', 'title': '5.1 Cumulative Subject Exposure in Clinical Trials', 'source': 'Report Structure'},
            {'id': 'sec-5.2', 'title': '5.2 Cumulative and Interval Patient Exposure from Marketing Experience', 'source': 'Report Structure'},
            {'id': 'sec-6.1', 'title': '6.1 Reference Safety Information (RSI) Revisions', 'source': 'Report Structure'},
            {'id': 'sec-7.1', 'title': '7.1 Summary Tabulations of Serious Adverse Events from Clinical Trials', 'source': 'Report Structure'},
            {'id': 'sec-7.2', 'title': '7.2 Cumulative & Interval Tabulations of Serious Adverse Reactions from Post-Marketing Sources', 'source': 'Report Structure'},
            {'id': 'sec-9.1', 'title': '9.1 Summary of Safety Signals', 'source': 'Report Structure'},
            {'id': 'sec-10', 'title': '10. Integrated Benefit-Risk Evaluation', 'source': 'Report Structure'},
        ]
    return outline[:250]


def summarize_profile(p: dict[str, Any]) -> dict[str, Any]:
    if p['kind'] == 'excel':
        return {
            'kind': 'excel',
            'sheets': [
                {
                    'sheet': s['sheet'],
                    'header_row': s['header_row'],
                    'columns': s['columns'],
                    'row_count': s['row_count'],
                    'preview': s['preview'][:10],
                }
                for s in p['sheets']
            ],
        }
    if p['kind'] == 'csv':
        return {k: p[k] for k in ('kind', 'columns', 'row_count', 'preview')}
    if p['kind'] == 'docx':
        return {'kind': 'docx', 'paragraphs': p['paragraphs'][:40], 'tables': p['tables'][:5]}
    return {'kind': p['kind'], 'pages': [{'page': x['page'], 'text': x['text'][:2000]} for x in p.get('pages', [])[:10]]}


def get_run(run_id: str, tenant_id: str | None = None) -> dict[str, Any]:
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, 'Run not found (POC runs are in-memory and reset on restart)')
    if tenant_id and tenant_id != run['tenant_id']:
        raise HTTPException(404, 'Run not found for tenant')
    return run


@app.post('/api/runs')
async def create_run(tenant_id: str = Form(...), target: UploadFile = File(...), sources: list[UploadFile] = File(...)):
    if not tenant_id.strip():
        raise HTTPException(400, 'tenant_id is required')
    if not sources:
        raise HTTPException(400, 'Upload at least one source document')

    run_id = uuid4().hex
    base = RUNTIME / run_id
    inp = base / 'input'
    work = base / 'work'
    inp.mkdir(parents=True)
    work.mkdir()

    manifest = []
    for role, uploads in [('target', [target]), ('source', sources)]:
        for upload in uploads:
            name = Path(upload.filename or 'upload').name
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED:
                shutil.rmtree(base, ignore_errors=True)
                raise HTTPException(415, f'Unsupported file: {name}')
            dest = inp / f"{uuid4().hex}_{name}"
            data = await upload.read()
            if len(data) > 100 * 1024 * 1024:
                shutil.rmtree(base, ignore_errors=True)
                raise HTTPException(413, 'File exceeds 100 MB')
            dest.write_bytes(data)
            manifest.append({
                'role': role,
                'filename': name,
                'stored_name': dest.name,
                'sha256': hashlib.sha256(data).hexdigest(),
                'size': len(data),
            })

    run = {
        'run_id': run_id,
        'tenant_id': tenant_id,
        'base_dir': base,
        'input_dir': inp,
        'work_dir': work,
        'manifest': manifest,
        'events': [],
        'profiles': {},
        'target_outline': [],
    }
    RUNS[run_id] = run

    for item in manifest:
        path = inp / item['stored_name']
        try:
            profile = extract_file(path)
            run['profiles'][item['stored_name']] = profile
            run['events'].append({
                'type': 'file_profiled',
                'file': item['filename'],
                'role': item['role'],
                'detail': f"Read {profile.get('kind', 'document')} structure",
            })
            if item['role'] == 'target':
                run['target_outline'] = build_outline(profile)
        except Exception as exc:
            run['events'].append({'type': 'profile_warning', 'file': item['filename'], 'detail': str(exc)})

    orchestrator = MultiAgentOrchestrator(run_id, base, inp, manifest, run['target_outline'])
    ORCHESTRATORS[run_id] = orchestrator

    return {
        'run_id': run_id,
        'tenant_id': tenant_id,
        'files': manifest,
        'target_outline': run['target_outline'],
        'profiles': {k: summarize_profile(v) for k, v in run['profiles'].items()},
        'events': run['events'],
    }


@app.post('/api/runs/demo')
def create_demo_pbrer_run(tenant_id: str = Form('pbrer-demo')):
    """One-click instant generator for realistic ICH E2C(R2) PBRER bundle."""
    run_id = uuid4().hex
    base = RUNTIME / run_id
    inp = base / 'input'
    work = base / 'work'
    inp.mkdir(parents=True)
    work.mkdir()

    demo_files = generate_pbrer_sample_bundle(inp)

    manifest = []
    target_p = demo_files['target']
    t_data = target_p.read_bytes()
    t_stored = f"{uuid4().hex}_{target_p.name}"
    (inp / t_stored).write_bytes(t_data)
    manifest.append({
        'role': 'target',
        'filename': target_p.name,
        'stored_name': t_stored,
        'sha256': hashlib.sha256(t_data).hexdigest(),
        'size': len(t_data),
    })

    for key in ['clinical', 'sales', 'icsr', 'signals']:
        src_p = demo_files[key]
        s_data = src_p.read_bytes()
        s_stored = f"{uuid4().hex}_{src_p.name}"
        (inp / s_stored).write_bytes(s_data)
        manifest.append({
            'role': 'source',
            'filename': src_p.name,
            'stored_name': s_stored,
            'sha256': hashlib.sha256(s_data).hexdigest(),
            'size': len(s_data),
        })

    run = {
        'run_id': run_id,
        'tenant_id': tenant_id,
        'base_dir': base,
        'input_dir': inp,
        'work_dir': work,
        'manifest': manifest,
        'events': [],
        'profiles': {},
        'target_outline': [],
    }
    RUNS[run_id] = run

    for item in manifest:
        path = inp / item['stored_name']
        try:
            profile = extract_file(path)
            run['profiles'][item['stored_name']] = profile
            run['events'].append({
                'type': 'file_profiled',
                'file': item['filename'],
                'role': item['role'],
                'detail': f"Profiled {profile.get('kind', 'file')} data",
            })
            if item['role'] == 'target':
                run['target_outline'] = build_outline(profile)
        except Exception as exc:
            run['events'].append({'type': 'profile_warning', 'file': item['filename'], 'detail': str(exc)})

    orchestrator = MultiAgentOrchestrator(run_id, base, inp, manifest, run['target_outline'])
    ORCHESTRATORS[run_id] = orchestrator

    return {
        'run_id': run_id,
        'tenant_id': tenant_id,
        'files': manifest,
        'target_outline': run['target_outline'],
        'profiles': {k: summarize_profile(v) for k, v in run['profiles'].items()},
        'events': run['events'],
    }


@app.post('/api/runs/{run_id}/launch-agents')
def launch_agents(run_id: str):
    run = get_run(run_id)
    orchestrator = ORCHESTRATORS.get(run_id)
    if not orchestrator:
        orchestrator = MultiAgentOrchestrator(run_id, run['base_dir'], run['input_dir'], run['manifest'], run['target_outline'])
        ORCHESTRATORS[run_id] = orchestrator

    # Launch in a background worker thread
    t = threading.Thread(target=orchestrator.run_autonomous_investigation, daemon=True)
    t.start()

    return {
        'status': 'launched',
        'run_id': run_id,
        'message': 'Autonomous Multi-Agent harness initiated. Streaming AG-UI telemetry.',
    }


@app.get('/api/runs/{run_id}/events')
def get_run_events(run_id: str, since_idx: int = 0):
    get_run(run_id)
    return {'events': ag_ui_manager.get_events(run_id, since_idx)}


@app.get('/api/runs/{run_id}/stream')
def stream_ag_ui(run_id: str):
    get_run(run_id)
    q = ag_ui_manager.subscribe_sync(run_id)

    def event_stream():
        try:
            # First send past events
            past = ag_ui_manager.get_events(run_id, 0)
            for evt_dict in past:
                yield f"data: {json.dumps(evt_dict)}\n\n"

            # Then stream new events
            while True:
                try:
                    evt = q.get(timeout=20)
                    yield evt.to_sse()
                except Exception:
                    # Keep-alive heartbeat
                    yield ": ping\n\n"
        finally:
            ag_ui_manager.unsubscribe_sync(run_id, q)

    return StreamingResponse(event_stream(), media_type='text/event-stream')


class UserNoteRequest(BaseModel):
    section_id: str
    note: str


@app.post('/api/runs/{run_id}/user-notes')
def add_user_note(run_id: str, payload: UserNoteRequest):
    run = get_run(run_id)
    orchestrator = ORCHESTRATORS.get(run_id)
    if not orchestrator:
        raise HTTPException(400, 'Agents have not been initialized for this run.')
    orchestrator.add_user_note(payload.section_id, payload.note)
    return {'status': 'note_received', 'section_id': payload.section_id, 'note': payload.note}


@app.get('/api/runs/{run_id}/mappings')
def get_mappings(run_id: str):
    run = get_run(run_id)
    orchestrator = ORCHESTRATORS.get(run_id)
    if not orchestrator:
        return {'mappings': []}
    return {
        'mappings': [
            {
                'section_id': m.section_id,
                'section_title': m.section_title,
                'status': m.status,
                'confidence': m.confidence,
                'mapped_sources': m.mapped_sources,
                'rules': m.rules,
                'metrics': m.computed_metrics,
                'user_notes': m.user_notes,
                'python_script': m.python_script,
            }
            for m in orchestrator.mappings.values()
        ]
    }


@app.get('/api/runs/{run_id}/sandbox-files')
def get_sandbox_files(run_id: str):
    run = get_run(run_id)
    orchestrator = ORCHESTRATORS.get(run_id)
    if not orchestrator:
        return {'files': []}
    return {'files': orchestrator.sandbox.list_files()}


@app.get('/api/runs/{run_id}/sandbox-files/{filename}')
def get_sandbox_file_content(run_id: str, filename: str):
    run = get_run(run_id)
    orchestrator = ORCHESTRATORS.get(run_id)
    if not orchestrator:
        raise HTTPException(404, 'Sandbox not found')
    try:
        content = orchestrator.sandbox.read_file(filename)
        return {'filename': filename, 'content': content}
    except Exception as exc:
        raise HTTPException(404, str(exc))


@app.get('/api/runs/{run_id}/sources/{stored_name}/preview')
def get_source_preview(run_id: str, stored_name: str):
    run = get_run(run_id)
    profile = run['profiles'].get(stored_name)
    if not profile:
        raise HTTPException(404, 'File profile not found')
    return profile


@app.get('/api/runs/{run_id}')
def run_detail(run_id: str, tenant_id: str | None = Header(None, alias='X-Tenant-ID')):
    r = get_run(run_id, tenant_id)
    return {
        'run_id': run_id,
        'tenant_id': r['tenant_id'],
        'files': r['manifest'],
        'target_outline': r['target_outline'],
        'profiles': {k: summarize_profile(v) for k, v in r['profiles'].items()},
        'events': r['events'],
    }


class MetricRequest(BaseModel):
    approved: bool = False
    source_filename: str
    metric_name: str
    sheet_name: str
    case_column: str
    event_column: str
    event_terms: list[str] = Field(min_length=1)
    initial_only: bool = False
    initial_flag_column: str = 'Derived-Initial-Follow-up-Flag'
    required_nonempty_columns: list[str] = Field(default_factory=list)
    date_column: str | None = None
    start_date_yyyymmdd: str | None = None
    end_date_yyyymmdd: str | None = None
    include_values: dict[str, list[str]] = Field(default_factory=dict)
    exclude_values: dict[str, list[str]] = Field(default_factory=dict)


@app.post('/api/runs/{run_id}/metrics')
def calculate_metric(run_id: str, request: MetricRequest, tenant_id: str | None = Header(None, alias='X-Tenant-ID')):
    run = get_run(run_id, tenant_id)
    if not request.approved:
        raise HTTPException(409, 'Rule must be explicitly approved before calculation')
    item = next((x for x in run['manifest'] if x['role'] == 'source' and x['filename'] == request.source_filename), None)
    if not item:
        raise HTTPException(404, 'Source file not found in this run')
    rule = EventMetricRule(
        metric_name=request.metric_name,
        sheet_name=request.sheet_name,
        case_column=request.case_column,
        event_column=request.event_column,
        event_terms=tuple(request.event_terms),
        initial_only=request.initial_only,
        initial_flag_column=request.initial_flag_column,
        required_nonempty_columns=tuple(request.required_nonempty_columns),
        date_column=request.date_column,
        start_date_yyyymmdd=request.start_date_yyyymmdd,
        end_date_yyyymmdd=request.end_date_yyyymmdd,
        include_values={k: tuple(v) for k, v in request.include_values.items()},
        exclude_values={k: tuple(v) for k, v in request.exclude_values.items()},
    )
    try:
        result = calculate_case_event_metric(run['input_dir'] / item['stored_name'], rule)
    except ValueError as e:
        raise HTTPException(422, str(e))
    result['approval'] = {
        'approved': True,
        'method': 'caller_assertion_local_poc',
        'reviewer_identity': None,
        'warning': 'No authenticated reviewer identity is implemented.',
    }
    result['source'] = {'filename': item['filename'], 'sha256': item['sha256']}
    artifact = f"metric_{uuid4().hex[:12]}.json"
    (run['work_dir'] / artifact).write_text(json.dumps(result, indent=2), encoding='utf-8')
    run['events'].append({
        'type': 'metric_calculated',
        'file': item['filename'],
        'detail': f"{result['numerator_distinct_cases']}/{result['denominator_distinct_cases']} distinct cases",
    })
    return {'artifact': artifact, 'result': result}


@app.get('/api/runs/{run_id}/artifacts/{artifact}')
def read_artifact(run_id: str, artifact: str, tenant_id: str | None = Header(None, alias='X-Tenant-ID')):
    run = get_run(run_id, tenant_id)
    if Path(artifact).name != artifact:
        raise HTTPException(400, 'Invalid artifact name')
    p = run['work_dir'] / artifact
    if not p.is_file():
        raise HTTPException(404, 'Artifact not found')
    return json.loads(p.read_text(encoding='utf-8'))
