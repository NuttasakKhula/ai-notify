import json
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

from psycopg.types.json import Jsonb

from db import database
import worker


PAYLOAD = {'seed_ip':'192.168.1.1','ssh_username':'test','ssh_password':'secret','max_depth':0}


def test_cancel_terminates_real_local_subprocess(browser, monkeypatch):
    alice = browser('alice')
    alice.post('/api/discoveries', json=PAYLOAD)
    job = worker.claim('discoveries')
    original = subprocess.Popen
    processes = []
    def launch(command, **kwargs):
        process = original([sys.executable, '-c', 'import time; time.sleep(30)'], **kwargs)
        processes.append(process)
        alice.post(f"/api/discoveries/{job['id']}/cancel")
        return process
    monkeypatch.setattr(worker.subprocess, 'Popen', launch)
    # taskkill itself must use the real Popen, so restore it after launching the child.
    def launch_once(command, **kwargs):
        process = launch(command, **kwargs)
        monkeypatch.setattr(worker.subprocess, 'Popen', original)
        return process
    monkeypatch.setattr(worker.subprocess, 'Popen', launch_once)
    worker.run_discovery(job)
    assert processes[0].poll() not in (None, 0), 'Child must be terminated, not allowed to finish its sleep'
    assert alice.get('/api/discoveries').json()[0]['status'] == 'cancelled'


def test_cancel_queued_is_scoped_and_idempotent(browser):
    alice, bob = browser('alice'), browser('bob')
    job = alice.post('/api/discoveries', json=PAYLOAD).json()
    url = f"/api/discoveries/{job['id']}/cancel"
    assert bob.post(url).status_code == 404
    assert alice.post(url).json()['status'] == 'cancelled'
    assert alice.post(url).json()['status'] == 'cancelled'
    assert worker.claim('discoveries') is None
    assert alice.post('/api/discoveries', json=PAYLOAD).status_code == 202


def test_running_cancel_kills_process_and_prevents_results(browser, monkeypatch):
    alice = browser('alice')
    alice.post('/api/discoveries', json=PAYLOAD)
    job = worker.claim('discoveries')
    killed = []

    class Process:
        pid = 123
        def poll(self): return None if not killed else 1
        def kill(self): killed.append(True)
        def communicate(self, data=None, timeout=None):
            if timeout is None: return '', ''
            assert json.loads(data)['password'] == 'secret'
            assert alice.post(f"/api/discoveries/{job['id']}/cancel").json()['status'] == 'cancelling'
            assert alice.post('/api/discoveries', json=PAYLOAD).status_code == 409
            assert alice.delete('/api/topology').status_code == 409
            raise subprocess.TimeoutExpired('test', 1)

    monkeypatch.setattr(worker.subprocess, 'Popen', lambda *args, **kwargs: Process())
    monkeypatch.setattr(worker.subprocess, 'run', lambda *args, **kwargs: killed.append(True))
    worker.run_discovery(job)
    assert killed
    assert alice.get('/api/discoveries').json()[0]['status'] == 'cancelled'
    assert alice.get('/api/topology').json() is None


def test_late_result_cannot_restore_reset_topology(browser, db_env, monkeypatch):
    alice = browser('alice')
    alice.post('/api/discoveries', json=PAYLOAD)
    job = worker.claim('discoveries')
    def finished(job_id, payload):
        alice.post(f'/api/discoveries/{job_id}/cancel')
        return SimpleNamespace(returncode=0, stdout=json.dumps({'snapshot':{'devices':{'SW':{'reachable':True}}},'vlans':{}}))
    monkeypatch.setattr(worker, 'discovery_process', finished)
    worker.run_discovery(job)
    assert alice.get('/api/discoveries').json()[0]['status'] == 'cancelled'
    with database() as conn:
        for _ in range(2):
            did = uuid4()
            conn.execute("INSERT INTO discoveries(id,client_id,created_by,seed_ip,ssh_username,ssh_password_encrypted,max_depth,status) VALUES(%s,%s,%s,'192.168.1.1','test','unused',0,'completed')", (did,db_env['org_a'],db_env['alice']))
            conn.execute('INSERT INTO topologies(id,client_id,discovery_id,snapshot,vlans) VALUES(%s,%s,%s,%s,%s)', (uuid4(),db_env['org_a'],did,Jsonb({'devices':{}}),Jsonb({})))
    assert browser('bob').delete(f"/api/topology?client_id={db_env['org_a']}").status_code == 403
    assert alice.get('/api/topology').json() is not None
    assert alice.delete('/api/topology').status_code == 200
    assert alice.get('/api/topology').json() is None
    assert len(alice.get('/api/discoveries').json()) == 3
