import pytest
from conftest import run

CASES = [('success','OK',200),('auth-missing','UPSTREAM_AUTH',401),('auth-invalid','UPSTREAM_AUTH',401),('permission-denied','UPSTREAM_PERMISSION',403),('throttled','UPSTREAM_THROTTLED',429),('timeout','UPSTREAM_TIMEOUT',None)]


@pytest.mark.parametrize('operation', ['agent_completion','knowledge_search'])
@pytest.mark.parametrize('scenario,code,status', CASES)
async def test_finite_scenarios(client, scenario, code, status, operation):
    item = await run(client, scenario, operation)
    obs = item['observation']
    assert item['provenance'] == 'synthetic'
    assert obs['code'] == code and obs['upstream_status'] == status
    assert obs['attempt_count'] == 1
    assert obs['retry_after_seconds'] == (7 if scenario == 'throttled' else None)
    assert obs['result_count'] == (1 if scenario == 'success' else None)
    assert obs['response_shape_valid'] == (True if scenario == 'success' else None)
    assert (await client.get('/v1/runs/'+item['id'])).json() == item


async def test_empty_and_invalid_scenarios(client):
    item = await run(client,'knowledge-empty','knowledge_search')
    assert item['status']=='succeeded' and item['observation']['code']=='OK_EMPTY'
    assert item['observation']['probe_expectation_met'] is False
    for scenario,op in [('unknown','agent_completion'),('knowledge-empty','agent_completion')]:
        response = await client.post('/v1/runs',json={'mode':'offline','operation':op,'scenario_id':scenario})
        assert response.status_code==422
    assert (await client.get('/v1/runs')).json()['total']==1
