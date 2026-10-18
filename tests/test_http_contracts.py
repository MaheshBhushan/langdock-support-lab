import asyncio
import json
import httpx
import pytest
from conftest import NOW
from langdock_support_lab.adapters.langdock import attempt, retry_hint, AGENT_TEXT, KNOWLEDGE_TEXT


@pytest.mark.parametrize('operation,path', [('agent_completion','/agent/v1/chat/completions'),('knowledge_search','/knowledge/search')])
async def test_exact_outgoing_contract(config, operation, path):
    calls=[]
    def handler(request):
        calls.append(request)
        fixture = 'agent-success.json' if operation=='agent_completion' else 'knowledge-success.json'
        return httpx.Response(200,content=(config.root/'fixtures'/fixture).read_bytes(),headers={'Content-Type':'application/json'})
    result=await attempt(operation,'run-id','dedicated-provider-canary','configured-agent',httpx.MockTransport(handler),lambda:NOW)
    assert result['code']=='OK' and len(calls)==1
    request=calls[0]
    assert str(request.url)=='https://api.langdock.com'+path and request.method=='POST'
    assert request.headers['authorization']=='Bearer dedicated-provider-canary'
    assert not any(t.encode() in request.content or t in str(request.headers) for t in config.tokens.values())
    body=json.loads(request.content)
    if operation=='agent_completion':
        assert body=={'agentId':'configured-agent','messages':[{'id':'msg_run-id','role':'user','parts':[{'type':'text','text':AGENT_TEXT}]}],'stream':False}
    else:
        assert body=={'query':KNOWLEDGE_TEXT}


BAD = [b'not json',b'{"messages":[{"id":"x","role":"assistant","content":"READY"}],"extra":1e999}',b'{"messages":[],"messages":[]}',b'{"messages":[{"id":"x","role":"assistant","content":5}]}',b'{"choices":[]}',b'{"messages":[{"id":"x","role":"assistant","parts":[]}]}',b'{"messages":[{"id":"x","role":"assistant","content":" "}]}',b'{"messages":[],"extra":NaN}',b'\xff',b' '*1048577]


@pytest.mark.parametrize('body', BAD)
async def test_bad_agent_payload_has_fixed_protocol_outcome(body):
    result=await attempt('agent_completion','id','key','agent',httpx.MockTransport(lambda r:httpx.Response(200,content=body,headers={'Content-Type':'application/json'})),lambda:NOW)
    assert result['code']=='UPSTREAM_PROTOCOL' and result['response_shape_valid'] is False
    assert 'messages' not in result


@pytest.mark.parametrize('changes', [{'similarity':float('inf')},{'similarity':True},{'index':True},{'index':-1},{'url':{}},{'id':''},{'subname':None}])
async def test_bad_knowledge_items(config,changes):
    data=json.loads((config.root/'fixtures/knowledge-success.json').read_text())
    data['result'][0].update(changes)
    result=await attempt('knowledge_search','id','key','agent',httpx.MockTransport(lambda r:httpx.Response(200,content=json.dumps(data).encode(),headers={'Content-Type':'application/json'})),lambda:NOW)
    assert result['code']=='UPSTREAM_PROTOCOL'


@pytest.mark.parametrize('status,code',[(201,'UPSTREAM_PROTOCOL'),(302,'UPSTREAM_PROTOCOL'),(404,'UPSTREAM_NOT_FOUND'),(418,'UPSTREAM_REJECTED'),(500,'UPSTREAM_UNAVAILABLE'),(524,'UPSTREAM_TIMEOUT')])
async def test_status_classification_no_retry(status,code):
    calls=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(status,content=b'private body',headers={'Location':'https://malicious.invalid'})
    result=await attempt('agent_completion','id','key','agent',httpx.MockTransport(handler),lambda:NOW)
    assert result['code']==code and len(calls)==1


@pytest.mark.parametrize('values,expected', [(['7'],7),(['999999'],300),(['-1'],None),(['0'],0),(['broken'],None),(['7','8'],None),(['9'*129],None),(['Mon, 19 Oct 2026 12:00:07 GMT'],7),(['Mon, 19 Oct 2026 11:59:00 GMT'],0)])
def test_retry_after(values,expected):
    assert retry_hint(httpx.Headers([('Retry-After',v) for v in values]),NOW)==expected


async def test_total_timeout_cancels_blocked_transport():
    cancelled=asyncio.Event()
    async def handler(request):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    result=await attempt('agent_completion','id','key','agent',httpx.MockTransport(handler),lambda:NOW,.02)
    assert result['code']=='UPSTREAM_TIMEOUT' and cancelled.is_set()


async def test_non_json_and_network():
    result=await attempt('agent_completion','id','key','agent',httpx.MockTransport(lambda r:httpx.Response(200,text='READY')),lambda:NOW)
    assert result['code']=='UPSTREAM_PROTOCOL'
    def failed(r):
        raise httpx.ConnectError('private exception key')
    result=await attempt('agent_completion','id','key','agent',httpx.MockTransport(failed),lambda:NOW)
    assert result['code']=='UPSTREAM_NETWORK' and 'private' not in json.dumps(result)


async def test_trickling_body_still_has_total_deadline():
    cancelled=asyncio.Event()
    class Trickling(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                while True:
                    yield b' '
                    await asyncio.sleep(.005)
            finally:
                cancelled.set()
    async def handler(request):
        return httpx.Response(200,headers={'Content-Type':'application/json'},stream=Trickling())
    result=await attempt('agent_completion','id','key','agent',httpx.MockTransport(handler),lambda:NOW,.02)
    assert result['code']=='UPSTREAM_TIMEOUT' and cancelled.is_set()


@pytest.mark.parametrize('operation,body', [('agent_completion',{'messages':[{'id':'x','role':'assistant','content':'READY'}]*101}),('knowledge_search',{'status':'success','result':[{}]*1001})])
async def test_array_bounds(operation,body):
    result=await attempt(operation,'id','key','agent',httpx.MockTransport(lambda r:httpx.Response(200,json=body)),lambda:NOW)
    assert result['code']=='UPSTREAM_PROTOCOL'
