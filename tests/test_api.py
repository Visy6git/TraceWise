from app.main import health, home, create_demo_pbrer_run, launch_agents, get_mappings, get_run_events


def test_health_and_endpoints():
    h = health()
    assert h['status'] == 'ok'

    html = home()
    assert 'tracewise' in html.lower()
    assert 'pbrer' in html.lower()


def test_demo_and_agent_execution():
    demo = create_demo_pbrer_run('test-tenant')
    assert 'run_id' in demo
    run_id = demo['run_id']
    assert len(demo['files']) == 5
    assert len(demo['target_outline']) > 0

    launched = launch_agents(run_id)
    assert launched['status'] == 'launched'

    mappings = get_mappings(run_id)['mappings']
    assert len(mappings) > 0
    sec5 = next((m for m in mappings if '5.1' in m['section_title']), None)
    assert sec5 is not None
