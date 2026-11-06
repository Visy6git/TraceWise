import json
import threading
import time
from pathlib import Path

from app.main import build_outline, focus_section_16_3
from app.services import agents
from app.services.agents import MultiAgentOrchestrator
from app.services.ag_ui import ag_ui_manager
from app.services.extractors import extract_file
from app.services.sample_pbrer import generate_pbrer_sample_bundle


def test_section_16_3_agents_run_concurrently_and_exchange_a2a_results(tmp_path, monkeypatch):
    base_dir = tmp_path / 'run'
    input_dir = base_dir / 'input'
    input_dir.mkdir(parents=True)
    work_dir = base_dir / 'work'
    work_dir.mkdir()
    files = generate_pbrer_sample_bundle(input_dir)
    manifest = [
        {
            'role': 'target' if key == 'target' else 'source',
            'filename': path.name,
            'stored_name': path.name,
            'sha256': 'test',
            'size': path.stat().st_size,
        }
        for key, path in files.items()
    ]
    profiles = {item['stored_name']: extract_file(input_dir / item['stored_name']) for item in manifest}
    outline = focus_section_16_3(build_outline(profiles[manifest[0]['stored_name']]))
    run_id = 'section-16-3-parallel-test'

    active_calls = 0
    max_active_calls = 0
    prompts = []
    call_lock = threading.Lock()

    def fake_sonnet(prompt, **kwargs):
        nonlocal active_calls, max_active_calls
        with call_lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            prompts.append(prompt)
        try:
            request = json.loads(prompt.split('\n\n', 1)[1])
            claims = []
            for section in request['sections']:
                source = next((source for source in section['sources'] if source['rows']), None)
                if source:
                    claims.append({
                        'section_id': section['section_id'],
                        'claim': f"Matched source evidence for {section['title']}.",
                        'source_filename': source['filename'],
                        'sheet': source['sheet'],
                        'row': source['rows'][0]['row'],
                    })
            time.sleep(0.08)
            return {
                'success': True,
                'text': json.dumps({'summary': 'Reviewed supplied preview evidence.', 'claims': claims}),
                'model_id': 'sonnet-test',
            }
        finally:
            with call_lock:
                active_calls -= 1

    monkeypatch.setenv('BEDROCK_ENABLED', 'true')
    monkeypatch.setattr(agents, 'is_bedrock_available', lambda: (True, 'available'))
    monkeypatch.setattr(agents, 'converse_sonnet', fake_sonnet)

    orchestrator = MultiAgentOrchestrator(run_id, base_dir, input_dir, manifest, outline, profiles)
    orchestrator.run_autonomous_investigation()

    events = ag_ui_manager.get_events(run_id)
    errors = [event for event in events if event['event_type'] == 'agent_error']
    assert not errors, [(event['summary'], event['details']) for event in errors]
    assert max_active_calls >= 2
    assert all(mapping.status == 'rules_compiled' for mapping in orchestrator.mappings.values())
    assert orchestrator.mappings['sec-16.3.1.2'].mapped_sources
    assert orchestrator.mappings['sec-16.3.1.2'].computed_metrics['claims']
    assert orchestrator.mappings['sec-16.3.2.1'].computed_metrics['model_id'] == 'sonnet-test'
    cardiac_sources = orchestrator.mappings['sec-16.3.1.1'].mapped_sources
    assert cardiac_sources
    assert all(source['filename'] != files['clinical'].name for source in cardiac_sources)
    assert cardiac_sources[0]['filters_applied']['rows_matched'] == 1
    assert all('NEX-ICSR-' not in prompt and 'Patient_Age' not in prompt for prompt in prompts)

    a2a_events = [event for event in events if event['event_type'] == 'a2a_message']
    assert len(a2a_events) >= 4
    assert all(event['details'].get('parallel') for event in a2a_events if event['details'].get('intent') == 'review_section_16_3_subtree')
    assert any(event['event_type'] == 'agent_filtering' for event in events)
    assert any(event['event_type'] == 'orchestration_status' and event['details']['status'] == 'completed' for event in events)
    assert any(file['name'] == 'complete_traceability_matrix.json' for file in orchestrator.sandbox.list_files())
