import pytest
from langdock_support_lab.config import Config, ConfigError, initialize


def test_init_refuses_overwrite_and_unsafe_credentials(root):
    path = root / '.local/credentials.json'
    original = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(FileExistsError):
        initialize(root)
    assert path.read_bytes() == original
    path.chmod(0o644)
    with pytest.raises(ConfigError):
        Config.load(root)
    path.chmod(0o600)
    renamed = path.with_suffix('.saved')
    path.rename(renamed)
    path.symlink_to(renamed)
    with pytest.raises(ConfigError):
        Config.load(root)


def test_offline_ignores_provider_file(root, monkeypatch):
    monkeypatch.setenv('LANGDOCK_API_KEY_FILE', '/must-not-read')
    assert Config.load(root).provider_key is None
    monkeypatch.setenv('LAB_MODE', 'live')
    with pytest.raises(ConfigError):
        Config.load(root)


@pytest.mark.parametrize('auth', [None, 'Bearer invalid', 'Basic invalid', 'Bearer ', 'bearer invalid'])
async def test_auth_before_body(client, auth):
    headers = {} if auth is None else {'Authorization': auth}
    response = await client.post('/v1/runs', headers={'Authorization': ''} | headers, content=b'invalid')
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'LOCAL_AUTH_REQUIRED'
    assert response.headers['www-authenticate'] == 'Bearer'
    assert (await client.get('/v1/runs')).json()['total'] == 0


async def test_duplicate_auth_roles_mode_docs(client, config):
    token = 'Bearer ' + config.tokens['operator']
    response = await client.get('/v1/scenarios', headers=[('Authorization', token), ('Authorization', token)])
    assert response.status_code == 401
    response = await client.post('/v1/runs', headers={'Authorization': 'Bearer '+config.tokens['reader']}, json={'mode':'offline','operation':'agent_completion','scenario_id':'success'})
    assert response.status_code == 403
    response = await client.post('/v1/runs', json={'mode':'live','operation':'agent_completion','probe_id':'health-text','acknowledge_live_request':True})
    assert response.status_code == 409
    assert (await client.get('/v1/runs')).json()['total'] == 0
    assert (await client.get('/healthz', headers={'Authorization':''})).json() == {'status':'ok'}
    assert (await client.get('/openapi.json', headers={'Authorization':''})).status_code == 401
    schema = (await client.get('/openapi.json')).json()
    assert schema['components']['securitySchemes']['HTTPBearer']['scheme'] == 'bearer'
    for path in ('/docs','/redoc'):
        assert (await client.get(path)).status_code == 404


async def test_live_mode_requires_admin_before_provider(config):
    import httpx
    from langdock_support_lab.app import create_app
    config.mode='live'
    config.provider_key='configured-provider-canary'
    config.agent_id='synthetic-test-agent'
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'messages':[{'id':'x','role':'assistant','content':'READY'}]})
    app=create_app(config,transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8765') as c:
            body={'mode':'live','operation':'agent_completion','probe_id':'health-text','acknowledge_live_request':True}
            for role in ('reader','operator'):
                response=await c.post('/v1/runs',json=body,headers={'Authorization':'Bearer '+config.tokens[role]})
                assert response.status_code==403 and calls==[]
            response=await c.post('/v1/runs',json=body,headers={'Authorization':'Bearer '+config.tokens['admin']})
            assert response.status_code==201 and len(calls)==1
            assert response.json()['provenance']=='live'
            # Mocked policy evidence does not satisfy the external live gate.


@pytest.mark.parametrize('value', ['short','x'*4097,'x'*16+'\nextra','x'*16+'\r','x'*16+'\0'])
def test_live_key_validation_fails_closed(root,monkeypatch,value):
    path=root/'.local/provider-key'
    path.write_text(value)
    path.chmod(0o600)
    monkeypatch.setenv('LAB_MODE','live')
    monkeypatch.setenv('LAB_LIVE_SCOPE_CONFIRMED','synthetic-only')
    monkeypatch.setenv('LANGDOCK_AGENT_ID','configured-agent')
    monkeypatch.setenv('LANGDOCK_API_KEY_FILE',str(path))
    with pytest.raises(ConfigError): Config.load(root)


def test_live_key_valid_and_symlink_rejected(root,monkeypatch):
    path=root/'.local/provider-key'
    path.write_text('synthetic-private-key-canary\n')
    path.chmod(0o600)
    monkeypatch.setenv('LAB_MODE','live')
    monkeypatch.setenv('LAB_LIVE_SCOPE_CONFIRMED','synthetic-only')
    monkeypatch.setenv('LANGDOCK_AGENT_ID','configured-agent')
    monkeypatch.setenv('LANGDOCK_API_KEY_FILE',str(path))
    assert Config.load(root).provider_key=='synthetic-private-key-canary'
    link=path.with_name('linked-provider-key'); link.symlink_to(path)
    monkeypatch.setenv('LANGDOCK_API_KEY_FILE',str(link))
    with pytest.raises(ConfigError): Config.load(root)
