import json
import os
import socket
import subprocess
import sys
import time
import httpx
import pytest


def invoke(root,*args,env=None):
    return subprocess.run([sys.executable,'-m','langdock_support_lab','--root',str(root),*args],capture_output=True,text=True,timeout=30,env=env)


def test_cli_real_loopback_workflow(root,tmp_path):
    try:
        sock = socket.socket()
        with sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
    except PermissionError:
        pytest.skip('A18 blocked: execution sandbox denies loopback TCP sockets')
    from langdock_support_lab.runbooks import IDS, review
    from langdock_support_lab.runs import utc_now
    for book_id in IDS:
        review(root,book_id,'synthetic-test-reviewer',180,utc_now())
    env=os.environ.copy(); env['LAB_PORT']=str(port); env['LAB_MODE']='offline'
    process=subprocess.Popen([sys.executable,'-m','langdock_support_lab','--root',str(root),'serve'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,env=env)
    try:
        # Bounded startup probes; no long wait or background log polling.
        for _ in range(100):
            try:
                with httpx.Client(trust_env=False,timeout=.1) as client:
                    if client.get(f'http://127.0.0.1:{port}/healthz').status_code==200: break
            except httpx.HTTPError:
                if process.poll() is not None: raise AssertionError('Server failed startup')
                time.sleep(.02)
        else: raise AssertionError('Server startup deadline')
        result=invoke(root,'scenarios','list',env=env)
        assert result.returncode==0 and len(json.loads(result.stdout)['items'])==7,result.stderr
        result=invoke(root,'run','--scenario','permission-denied','--operation','agent_completion',env=env)
        assert result.returncode==3 and json.loads(result.stdout)['status']=='failed'
        result=invoke(root,'--role','reader','run','--scenario','success','--operation','agent_completion',env=env)
        assert result.returncode==4
        result=invoke(root,'smoke','--json',env=env)
        assert result.returncode==0,result.stderr
        data=json.loads(result.stdout)
        assert data['offline_acceptance']=='passed' and data['live_gate']=='unverified'
        result=invoke(root,'incidents','export',data['incident_id'],'--out',str(root/'.local/exports'),env=env)
        assert result.returncode==0,result.stderr
        result=invoke(root,'--role','admin','live','verify','--acknowledge-live-request',env=env)
        assert result.returncode==7 and json.loads(result.stdout)['live_gate']=='unverified'
        tokens=json.loads((root/'.local/credentials.json').read_text())
        for key,value in tokens.items():
            if key.endswith('_token'): assert value not in result.stdout+result.stderr
    finally:
        process.terminate()
        process.wait(timeout=5)
