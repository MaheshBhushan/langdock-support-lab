from datetime import datetime, timezone
import shutil
import socket
from pathlib import Path
import pytest
import httpx
from langdock_support_lab.config import Config, initialize
from langdock_support_lab.app import create_app
from langdock_support_lab.runbooks import IDS, review

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_external_sockets(monkeypatch):
    original = socket.socket.connect

    def guarded(sock, address):
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original(sock, address)
        raise AssertionError('External socket denied in local acceptance')

    monkeypatch.setattr(socket.socket, 'connect', guarded)
    original_ex = socket.socket.connect_ex

    def guarded_ex(sock, address):
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original_ex(sock, address)
        raise AssertionError('External socket denied in local acceptance')

    monkeypatch.setattr(socket.socket, 'connect_ex', guarded_ex)
    original_dns = socket.getaddrinfo

    def guarded_dns(host, *args, **kwargs):
        if host in ('127.0.0.1', '::1', 'localhost'):
            return original_dns(host, *args, **kwargs)
        raise AssertionError('External DNS denied in local acceptance')

    monkeypatch.setattr(socket, 'getaddrinfo', guarded_dns)



@pytest.fixture
def root(tmp_path):
    source = Path(__file__).resolve().parents[1]
    shutil.copy(source / 'pyproject.toml', tmp_path)
    shutil.copytree(source / 'fixtures', tmp_path / 'fixtures')
    shutil.copytree(source / 'runbooks', tmp_path / 'runbooks')
    initialize(tmp_path)
    for book_id in IDS:
        review(tmp_path, book_id, 'synthetic-test-reviewer', 180, NOW)
    return tmp_path


@pytest.fixture
def config(root):
    return Config.load(root)


@pytest.fixture
async def client(config):
    app = create_app(config, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8765', headers={'Authorization': 'Bearer ' + config.tokens['operator']}) as client:
            client.lab = app
            yield client


async def run(client, scenario='permission-denied', operation='agent_completion'):
    response = await client.post('/v1/runs', json={'mode': 'offline', 'operation': operation, 'scenario_id': scenario})
    assert response.status_code == 201, response.text
    return response.json()
