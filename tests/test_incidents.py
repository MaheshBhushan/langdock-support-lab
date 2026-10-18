import asyncio
from datetime import timedelta
from conftest import NOW, run


async def create(client):
    failed=await run(client)
    response=await client.post('/v1/incidents',json={'run_id':failed['id'],'title':'Local custom title'})
    assert response.status_code==201
    return response.json(),failed


async def change(client,item,kind,**fields):
    response=await client.post('/v1/incidents/'+item['id']+'/events',json={'type':kind,'expected_version':item['version'],**fields})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['version']==item['version']+1
    return result


async def triage(client,item):
    response=await client.post('/v1/incidents/'+item['id']+'/triage',json={'expected_version':item['version']})
    assert response.status_code==200,response.text
    return response.json()


async def test_complete_lifecycle_and_recurrence(client):
    item,failed=await create(client)
    item=await change(client,item,'check',check_id='agent_shared',result='unknown')
    item=await triage(client,item)
    assert item['triage']['level']=='L2' and item['triage']['recommended_action']=='escalate'
    assert item['triage']['citations'][0]['runbook_id']=='RB-PERMISSION'
    item=await change(client,item,'escalate',reason='admin_access_required')
    client.lab.state.runs.clock=lambda:NOW+timedelta(seconds=1)
    success=await run(client,'success')
    item=await change(client,item,'attach_run',run_id=success['id'])
    assert item['triage'] is None
    item=await triage(client,item)
    assert item['triage']['recommended_action']=='verify_recovery'
    client.lab.state.incidents.clock=lambda:NOW+timedelta(seconds=2)
    item=await change(client,item,'resolve',verification_run_id=success['id'],resolution='synthetic_recovery_verified')
    assert item['state']=='resolved'
    client.lab.state.runs.clock=lambda:NOW+timedelta(seconds=3)
    recurring=await run(client)
    item=await change(client,item,'attach_run',run_id=recurring['id'])
    item=await change(client,item,'reopen',reason='recurrence')
    assert item['state']=='open' and item['run_ids']==[failed['id'],success['id'],recurring['id']]
    assert [e['sequence'] for e in item['events']]==list(range(1,item['version']+1))


async def test_atomic_version_and_invalid_transitions(client):
    item,failed=await create(client)
    duplicate=await client.post('/v1/incidents',json={'run_id':failed['id']})
    assert duplicate.status_code==409
    path='/v1/incidents/'+item['id']+'/events'
    bad=await client.post(path,json={'type':'escalate','expected_version':1,'reason':'admin_access_required'})
    assert bad.status_code==409
    bodies=[{'type':'check','expected_version':1,'check_id':'agent_shared','result':r} for r in ('pass','unknown')]
    results=await asyncio.gather(*[client.post(path,json=b) for b in bodies])
    assert sorted(r.status_code for r in results)==[200,409]
    current=(await client.get('/v1/incidents/'+item['id'])).json()
    assert current['version']==2 and len(current['events'])==2
    response=await client.post(path,json={'type':'check','expected_version':2,'check_id':'knowledge_viewer_shared','result':'pass'})
    assert response.status_code==422
    response=await client.post(path,json={'type':'attach_run','expected_version':2,'run_id':failed['id']})
    assert response.status_code==409
    cross=await run(client,'success','knowledge_search')
    response=await client.post(path,json={'type':'attach_run','expected_version':2,'run_id':cross['id']})
    assert response.status_code==422


async def test_recovery_requires_newer_nonempty_and_fresh_triage(client):
    item,_=await create(client)
    item=await triage(client,item)
    success=await run(client,'success')
    item=await change(client,item,'attach_run',run_id=success['id'])
    response=await client.post('/v1/incidents/'+item['id']+'/events',json={'type':'resolve','expected_version':item['version'],'verification_run_id':success['id'],'resolution':'synthetic_recovery_verified'})
    assert response.status_code==409
    item=await triage(client,item)
    assert item['triage']['recommended_action']!='verify_recovery'
    response=await client.post('/v1/incidents',json={'run_id':success['id']})
    assert response.status_code==409


async def test_history_citations_survive_review_invalidation(client,root):
    item,_=await create(client)
    item=await triage(client,item)
    path='/v1/incidents/'+item['id']+'/bundle?format=json'
    before=(await client.get(path)).content
    book=root/'runbooks/RB-PERMISSION.md'
    book.write_text(book.read_text()+'\nUnreviewed modification.\n')
    assert (await client.get(path)).content==before
    fresh=await triage(client,item)
    assert fresh['triage']['citations']==[]
    assert 'No eligible reviewed guidance available' in fresh['triage']['limitations']
    assert fresh['triage']['recommended_action']=='escalate'
