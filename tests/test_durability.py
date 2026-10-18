import asyncio
import httpx
import pytest
from conftest import NOW, run
from langdock_support_lab.app import create_app
from langdock_support_lab.errors import LabError
from langdock_support_lab.models import Offline
from langdock_support_lab.storage import Storage


async def test_finalize_failure_recovery_without_replay(client,config,monkeypatch):
    db=client.lab.state.storage
    completed=await run(client,'success')
    original=db.finalize_run
    def fail(item): raise LabError('STORAGE_UNAVAILABLE',503)
    monkeypatch.setattr(db,'finalize_run',fail)
    response=await client.post('/v1/runs',json={'mode':'offline','operation':'agent_completion','scenario_id':'timeout'})
    assert response.status_code==503
    assert any(r['status']=='running' for r in (await client.get('/v1/runs')).json()['items'])
    monkeypatch.setattr(db,'finalize_run',original)
    reopened=Storage(config.root/'.local/state.sqlite3')
    reopened.recover('2026-10-19T12:01:00.000Z')
    items=reopened.listing('runs',50,0)['items']
    assert len(items)==2 and reopened.run(completed['id'])['status']=='succeeded'
    assert [r['observation']['code'] for r in items].count('RUN_INTERRUPTED')==1


async def test_capacity_and_cancellation_release_slots(config):
    entered=asyncio.Event()
    active=0
    async def handler(request):
        nonlocal active
        active+=1
        if active==4: entered.set()
        await asyncio.Event().wait()
    app=create_app(config,clock=lambda:NOW,transport=httpx.MockTransport(handler))
    service=app.state.runs
    request=Offline(mode='offline',operation='agent_completion',scenario_id='success')
    async with app.router.lifespan_context(app):
        tasks=[asyncio.create_task(service.create(request)) for _ in range(4)]
        await asyncio.wait_for(entered.wait(),2)
        with pytest.raises(LabError) as exc:
            await asyncio.wait_for(service.create(request),.1)
        assert exc.value.code=='LOCAL_CAPACITY'
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        assert service.active==0
        assert all(r['status']=='interrupted' for r in app.state.storage.listing('runs',50,0)['items'])
        service.transport=httpx.MockTransport(lambda r:httpx.Response(403))
        assert (await service.create(request))['observation']['code']=='UPSTREAM_PERMISSION'
