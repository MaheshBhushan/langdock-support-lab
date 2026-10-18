import json
from pathlib import Path
import pytest
from test_incidents import create, change, triage
from langdock_support_lab.bundles import write_pair
from langdock_support_lab.errors import LabError


async def test_stable_bundle_snapshot_custom_title_omitted(client,tmp_path):
    item,_=await create(client)
    item=await change(client,item,'check',check_id='agent_shared',result='unknown')
    item=await triage(client,item)
    pair=[]
    for fmt in ('json','markdown'):
        response=await client.get('/v1/incidents/'+item['id']+'/bundle?format='+fmt)
        assert response.status_code==200
        assert 'Local custom title' not in response.text
        assert response.content==(await client.get('/v1/incidents/'+item['id']+'/bundle?format='+fmt)).content
        pair.append(response.content)
    data=json.loads(pair[0])
    assert data['redaction']['custom_title_omitted'] is True
    assert data['reviewed_guidance'][0]['review_status_at_triage']=='eligible'
    target=write_pair(tmp_path/'exports',*pair)
    assert (Path(target['directory'])/'incident.json').read_bytes()==pair[0]
    with pytest.raises(LabError): write_pair(tmp_path/'exports',*pair)
    link=tmp_path/'linked'; link.symlink_to(tmp_path/'exports',target_is_directory=True)
    with pytest.raises(LabError): write_pair(link,*pair)
    await change(client,item,'check',check_id='required_scope_confirmed',result='pass')
    new_md=(await client.get('/v1/incidents/'+item['id']+'/bundle?format=markdown')).content
    with pytest.raises(LabError) as exc: write_pair(tmp_path/'mixed',pair[0],new_md)
    assert exc.value.code=='VERSION_CONFLICT' and not (tmp_path/'mixed').exists()


def test_public_example_is_synthetic_and_has_no_private_fields():
    root=Path(__file__).resolve().parents[1]
    data=json.loads((root/'examples/synthetic-escalation.json').read_text())
    assert data['bundle_kind']=='synthetic-escalation'
    assert all(r['provenance']=='synthetic' for r in data['evidence'])
    assert data['redaction']['raw_payloads_included'] is False
    forbidden={'authorization','provider_key','agentId','url','content','reviewer','credentials','raw_body'}
    def scan(value):
        if isinstance(value,dict):
            assert not forbidden & set(value)
            for child in value.values(): scan(child)
        elif isinstance(value,list):
            for child in value: scan(child)
    scan(data)
    for filename in ('synthetic-escalation.json','synthetic-escalation.md'):
        text=(root/'examples'/filename).read_text()
        assert all(s not in text for s in ('/home/','/run/media/','.local/','Bearer ','provider-canary-value','header-canary-value'))
