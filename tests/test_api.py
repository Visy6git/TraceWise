import asyncio
import io
import shutil

from starlette.datastructures import UploadFile

from app.main import (
    RUNS,
    ORCHESTRATORS,
    build_outline,
    focus_section_16_3,
    health,
    home,
    create_run,
    create_demo_pbrer_run,
    get_target_document,
    launch_agents,
    get_mappings,
    get_source_preview,
    stream_ag_ui,
    app,
)
from app.services.ag_ui import ag_ui_manager
from app.services.sample_pbrer import generate_pbrer_sample_bundle


def test_health_and_endpoints():
    h = health()
    assert h['status'] == 'ok'

    html = home()
    assert 'tracewise' in html.lower()
    assert 'pbrer' in html.lower()


def test_agent_stream_closes_after_terminal_orchestration_event(monkeypatch):
    run_id = 'terminal-stream-test'
    monkeypatch.setitem(RUNS, run_id, {'tenant_id': 'test-tenant'})
    ag_ui_manager.emit(
        run_id,
        'orchestrator',
        'PBRER Orchestrator',
        'Lead Orchestrator',
        'orchestration_status',
        'Section 16.3 parallel review finished.',
        {'status': 'completed'},
    )
    response = stream_ag_ui(run_id)

    try:
        underlying = response.body_iterator.ag_frame.f_locals.get('iterator')
        chunks = list(underlying) if underlying else []
    except Exception:
        async def consume():
            return [chunk async for chunk in response.body_iterator]
        chunks = asyncio.run(consume())

    assert len(chunks) == 1
    assert '"status": "completed"' in chunks[0]


def test_upload_stores_long_source_filenames_without_exceeding_windows_path_limit(tmp_path):
    sample_files = generate_pbrer_sample_bundle(tmp_path)
    long_filename = (
        '02_case_Impulse control disorders such as compulsive shopping_pathological gambling_'
        'hypersexuality_binge eating and other impulse_CSMR.xlsx'
    )
    target_up = UploadFile(
        filename=sample_files['target'].name,
        file=io.BytesIO(sample_files['target'].read_bytes()),
    )
    source_up = UploadFile(
        filename=long_filename,
        file=io.BytesIO(sample_files['clinical'].read_bytes()),
    )

    result = create_run(
        tenant_id='long-filename-test',
        target=target_up,
        sources=[source_up],
    )

    run_id = result['run_id']
    try:
        uploaded_source = next(item for item in result['files'] if item['role'] == 'source')
        assert uploaded_source['filename'] == long_filename
        assert uploaded_source['stored_name'].endswith('.xlsx')
        assert len(uploaded_source['stored_name']) < 50
        assert (RUNS[run_id]['input_dir'] / uploaded_source['stored_name']).is_file()
    finally:
        orch = ORCHESTRATORS.get(run_id)
        if orch and hasattr(orch, 'data_engine'):
            orch.data_engine.close()
        shutil.rmtree(RUNS[run_id]['base_dir'], ignore_errors=True)
        RUNS.pop(run_id, None)
        ORCHESTRATORS.pop(run_id, None)


def test_demo_is_scoped_to_section_16_3_and_renders_full_report(monkeypatch):
    from app.services.agents import MultiAgentOrchestrator

    monkeypatch.setattr(MultiAgentOrchestrator, 'run_autonomous_investigation', lambda self: None)
    demo = create_demo_pbrer_run('test-tenant')
    assert 'run_id' in demo
    run_id = demo['run_id']
    try:
        assert len(demo['files']) == 5
        assert len(demo['profiles']) == 5
        assert demo['target_outline'][0]['section_number'] == '16.3'
        assert all(item['section_number'].startswith('16.3') for item in demo['target_outline'])
        for source in (file for file in demo['files'] if file['role'] == 'source'):
            preview = get_source_preview(run_id, source['stored_name'])
            assert preview['kind'] == 'excel'

        report = get_target_document(run_id)
        assert report['kind'] == 'docx'
        assert len(report['blocks']) > 30
        assert any('10. Integrated Benefit-Risk' in block.get('text', '') for block in report['blocks'])

        launched = launch_agents(run_id)
        assert launched['status'] == 'launched'
        assert len(get_mappings(run_id)['mappings']) == len(demo['target_outline'])
    finally:
        orch = ORCHESTRATORS.get(run_id)
        if orch and hasattr(orch, 'data_engine'):
            orch.data_engine.close()
        for p in RUNS[run_id]['base_dir'].rglob('*'):
            try:
                p.chmod(0o777)
            except Exception:
                pass
        shutil.rmtree(RUNS[run_id]['base_dir'], ignore_errors=True)
        RUNS.pop(run_id, None)
        ORCHESTRATORS.pop(run_id, None)


def test_outline_uses_report_headings_and_builds_nested_sections():
    outline = build_outline({
        'paragraphs': [
            {'paragraph': 1, 'text': 'PBRER COVER TITLE', 'style': 'Title'},
            {'paragraph': 2, 'text': '5 EXPOSURE', 'style': 'Heading 1'},
            {'paragraph': 3, 'text': '5.1 Clinical exposure', 'style': 'Heading 2'},
            {'paragraph': 4, 'text': '5.1.1 Ongoing studies', 'style': 'Heading 3'},
            {'paragraph': 5, 'text': '2024 cases were reviewed.', 'style': 'Normal'},
        ],
    })

    assert [item['title'] for item in outline] == [
        '5 EXPOSURE',
        '5.1 Clinical exposure',
        '5.1.1 Ongoing studies',
    ]
    assert outline[1]['parent_id'] == outline[0]['id']
    assert outline[2]['parent_id'] == outline[1]['id']
    assert build_outline({'paragraphs': [{'paragraph': 1, 'text': 'Ordinary narrative text', 'style': 'Normal'}]}) == []


def test_focus_outline_numbers_styled_section_16_hierarchy():
    outline = build_outline({
        'paragraphs': [
            {'paragraph': 1, 'text': 'SIGNAL AND RISK EVALUATION', 'style': 'CS 1ST LEVEL autono'},
            {'paragraph': 2, 'text': 'SUMMARY OF SAFETY CONCERNS', 'style': 'CS 2ND LEVEL autono'},
            {'paragraph': 3, 'text': 'SIGNAL EVALUATION', 'style': 'CS 2ND LEVEL autono'},
            {'paragraph': 4, 'text': 'EVALUATION OF RISKS AND NEW INFORMATION', 'style': 'CS 2ND LEVEL autono'},
            {'paragraph': 5, 'text': 'New information on important identified risks', 'style': 'CS 3RD LEVEL autono'},
            {'paragraph': 6, 'text': 'Cardiac failure', 'style': 'CS 4TH LEVEL autono'},
            {'paragraph': 7, 'text': 'CHARACTERISATION OF RISKS', 'style': 'CS 2ND LEVEL autono'},
        ],
    })

    focused = focus_section_16_3(outline)
    assert [item['section_number'] for item in focused] == ['16.3', '16.3.1', '16.3.1.1']
    assert focused[0]['title'] == 'EVALUATION OF RISKS AND NEW INFORMATION'
    assert focused[1]['parent_id'] == 'sec-16.3'
    assert focused[2]['parent_id'] == 'sec-16.3.1'
    assert focus_section_16_3(build_outline({'paragraphs': []})) == []
