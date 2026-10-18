"""Regenerate public synthetic artifacts with fixed IDs/time and reviewed local files."""
import asyncio
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
import shutil
import tempfile
from uuid import UUID
import httpx
from langdock_support_lab.app import create_app
from langdock_support_lab.config import Config, initialize


async def main():
    source = Path(__file__).resolve().parents[1]
    fixed = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    sequence = count(1)
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        shutil.copy(source / 'pyproject.toml', root)
        for folder in ('fixtures', 'runbooks'):
            shutil.copytree(source / folder, root / folder)
        initialize(root)
        app = create_app(Config.load(root), clock=lambda: fixed, uuid=lambda: UUID(int=next(sequence)))
        async with app.router.lifespan_context(app):
            token = Config.load(root).tokens['operator']
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8765', headers={'Authorization': 'Bearer ' + token}) as client:
                response = await client.post('/v1/runs', json={'mode': 'offline', 'operation': 'agent_completion', 'scenario_id': 'permission-denied'})
                response.raise_for_status()
                failed = response.json()
                # The fixture records deterministic timing, independent of machine speed.
                failed['observation']['duration_ms'] = 0
                app.state.storage.finalize_run(failed)
                response = await client.post('/v1/incidents', json={'run_id': failed['id']})
                response.raise_for_status()
                item = response.json()
                response = await client.post('/v1/incidents/' + item['id'] + '/events', json={'type': 'check', 'expected_version': 1, 'check_id': 'agent_shared', 'result': 'unknown'})
                response.raise_for_status()
                response = await client.post('/v1/incidents/' + item['id'] + '/triage', json={'expected_version': 2})
                response.raise_for_status()
                if not response.json()['triage']['citations']:
                    raise ValueError('Eligible synthetic review required at fixed example date')
                response = await client.post('/v1/incidents/' + item['id'] + '/events', json={'type': 'escalate', 'expected_version': 3, 'reason': 'admin_access_required'})
                response.raise_for_status()
                for fmt, ext in (('json', 'json'), ('markdown', 'md')):
                    response = await client.get('/v1/incidents/' + item['id'] + '/bundle?format=' + fmt)
                    response.raise_for_status()
                    (source / 'examples' / ('synthetic-escalation.' + ext)).write_bytes(response.content)
    print('Generated two synthetic example artifacts; no provider request occurred.')


if __name__ == '__main__':
    asyncio.run(main())
