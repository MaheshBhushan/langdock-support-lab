import json
import httpx
import pytest
from conftest import run, NOW
from langdock_support_lab.app import create_app


@pytest.mark.parametrize('content,status', [(b'{',400),(b'{"x":1e999}',400),(b'{"mode":"offline","mode":"offline"}',400),(b'{"x":NaN}',400),(b'x'*16385,413)])
async def test_invalid_bodies_do_not_create_runs(client,content,status):
    response=await client.post('/v1/runs',content=content,headers={'Content-Type':'application/json'})
    assert response.status_code==status
    assert (await client.get('/v1/runs')).json()['total']==0


async def test_boundaries_unknown_fields_queries_origin_host(client):
    body={'mode':'offline','operation':'agent_completion','scenario_id':'success','secret_unknown':'sentinel-private'}
    response=await client.post('/v1/runs',json=body)
    assert response.status_code==422 and 'sentinel-private' not in response.text and 'secret_unknown' not in response.text
    for path in ('/v1/scenarios?extra=1','/v1/runs?limit=0','/v1/runs/not-an-id','/v1/runs?limit=1&limit=2'):
        assert (await client.get(path)).status_code==422
    assert (await client.get('/healthz',headers={'Origin':'null'})).status_code==403
    assert (await client.get('/healthz',headers={'Host':'evil.invalid'})).status_code==400
    assert (await client.request('GET','/v1/scenarios',content=b'body')).status_code==400
    assert (await client.post('/v1/runs',content=b'{}')).status_code==415
    assert (await client.get('/v1/runs')).json()['total']==0


async def test_chunked_limit(client):
    async def chunks():
        yield b'a'*10000
        yield b'b'*10000
    response=await client.post('/v1/runs',content=chunks(),headers={'Content-Type':'application/json'})
    assert response.status_code==413


@pytest.mark.parametrize('input_kind',['title','question'])
async def test_sensitive_free_text_not_echoed(client,config,input_kind):
    failed=await run(client)
    for sentinel in [config.tokens['reader'],'Bearer canary-auth-sentinel','api_key=canary-secret-sentinel','-----BEGIN PRIVATE KEY-----']:
        if input_kind=='title':
            response=await client.post('/v1/incidents',json={'run_id':failed['id'],'title':sentinel})
        else:
            response=await client.post('/v1/support/ask',json={'question':sentinel})
        assert response.status_code==422 and sentinel not in response.text
    db=client.lab.state.storage
    with db.connection() as conn:
        assert conn.execute('SELECT count(*) FROM incidents').fetchone()[0]==0


@pytest.mark.parametrize('kind',['body','exception','header','valid'])
async def test_provider_canaries_never_persist_or_export(config,caplog,kind):
    sentinels=['provider-canary-value','Bearer header-canary-value','https://private.invalid/canary-file',config.tokens['admin']]
    config.provider_key=sentinels[0]
    def handler(request):
        if kind=='exception': raise httpx.ConnectError(' '.join(sentinels))
        if kind=='header': return httpx.Response(403,headers={'X-Private':' '.join(sentinels)},text=' '.join(sentinels))
        if kind=='valid': return httpx.Response(200,json={'messages':[{'id':sentinels[2],'role':'assistant','content':' '.join(sentinels)}]})
        return httpx.Response(200,content=(' '.join(sentinels)).encode(),headers={'Content-Type':'application/json'})
    app=create_app(config,clock=lambda:NOW,transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765',headers={'Authorization':'Bearer '+config.tokens['operator']}) as client:
            item=await run(client)
            outputs=[json.dumps(item)]
            if item['status']=='failed':
                incident=(await client.post('/v1/incidents',json={'run_id':item['id']})).json()
                for fmt in ('json','markdown'):
                    outputs.append((await client.get('/v1/incidents/'+incident['id']+'/bundle?format='+fmt)).text)
            with app.state.storage.connection() as conn:
                outputs.append('\n'.join(conn.iterdump()))
            outputs.append(caplog.text)
            for sentinel in sentinels:
                assert all(sentinel not in output for output in outputs)
