import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from api import app
from db import database, migrate
from security import cipher
import worker


def ingest(client, key='key-a', event='incident-1', device='SW-A'):
    return client.post('/webhook/incident', headers={'X-Webhook-Key':key, 'Idempotency-Key':event},
                       json={'device_name':device,'matches':[{'message':'Interface Gi1/0/1 link down','@timestamp':'2026-09-20T12:00:00Z','severity':'critical'}]})


def test_migrations_are_repeatable(db_env):
    migrate()
    with database() as conn:
        assert conn.execute('SELECT version FROM schema_migrations ORDER BY version').fetchall() == [{'version':1}, {'version':2}, {'version':3}, {'version':4}, {'version':5}, {'version':6}, {'version':7}, {'version':8}, {'version':9}]


def test_login_logout_roles_and_csrf(browser, db_env):
    anon = TestClient(app)
    assert anon.get('/api/auth/me').status_code == 401
    assert anon.post('/api/auth/login',json={'email':'alice@example.test','password':'test-password-123'}).status_code == 403
    alice = browser('alice')
    assert alice.get('/api/auth/me').json()['role'] == 'Employee'
    assert alice.patch('/api/settings',json={'notify_enabled':True}).status_code == 403
    assert alice.post('/api/clients',json={'name':'forbidden'}).status_code == 403
    assert alice.get('/api/users').status_code == 403
    assert alice.post('/api/auth/logout').status_code == 200
    assert alice.get('/api/auth/me').status_code == 401


def test_failed_logins_are_rate_limited(db_env):
    client = TestClient(app,headers={'X-Requested-With':'ai-notify'})
    for _ in range(10):
        assert client.post('/api/auth/login',json={'email':'alice@example.test','password':'wrong'}).status_code == 401
    assert client.post('/api/auth/login',json={'email':'alice@example.test','password':'test-password-123'}).status_code == 429


def test_organization_isolation_shared_data_and_filtering(browser, db_env):
    admin, alice, amy, bob = browser(), browser('alice'), browser('amy'), browser('bob')
    result = ingest(admin)
    assert result.status_code == 202, result.text
    for colleague in (alice,amy):
        assert colleague.get('/api/logs').json()['total'] == 1
    assert bob.get('/api/logs').json()['total'] == 0
    assert alice.get('/api/logs',params={'client_id':str(db_env['org_b'])}).status_code == 403
    assert bob.get('/api/dashboard').json()['counts']['logs'] == 0
    assert alice.get('/api/dashboard').json()['counts']['logs'] == 1
    assert alice.get('/api/logs',params={'q':'no-match'}).json()['total'] == 0
    assert alice.get('/api/logs',params={'device':'SW-A','start':'2026-09-20T00:00:00Z','end':'2026-09-20T23:59:59Z'}).json()['total'] == 1
    assert alice.get('/api/logs',params={'start':'2026-09-21T00:00:00Z'}).json()['total'] == 0
    original = alice.get('/api/logs').json()['items'][0]['original_id']
    assert amy.get(f'/api/logs/{original}/original').status_code == 200
    assert bob.get(f'/api/logs/{original}/original').status_code == 403


def test_webhook_auth_validation_dedup_and_paused_ingestion(browser):
    client = browser()
    assert ingest(client,key='wrong').status_code == 401
    assert client.post('/webhook/incident',headers={'X-Webhook-Key':'key-a'},json={'matches':[]}).status_code == 422
    first, second = ingest(client), ingest(client)
    assert first.json()['id'] == second.json()['id']
    assert first.json()['status'] == 'suppressed'
    assert worker.claim('reports') is None
    with database() as conn:
        assert conn.execute('SELECT count(*) AS n FROM original_logs').fetchone()['n'] == 1
        assert conn.execute('SELECT count(*) AS n FROM log_history').fetchone()['n'] == 1


def test_discovery_encryption_worker_persistence_and_isolation(browser,db_env,monkeypatch):
    alice = browser('alice')
    payload = {'seed_ip':'192.168.1.1','ssh_username':'netops','ssh_password':'super-secret','max_depth':2}
    assert alice.post('/api/discoveries',json={**payload,'seed_ip':'127.0.0.1'}).status_code == 422
    assert alice.post('/api/discoveries',json={**payload,'seed_ip':'bad-ip'}).status_code == 422
    started = alice.post('/api/discoveries',json=payload)
    assert started.status_code == 202, started.text
    assert alice.post('/api/discoveries',json=payload).status_code == 409
    listing = alice.get('/api/discoveries').text
    assert 'super-secret' not in listing and 'ssh_password' not in listing
    job = worker.claim('discoveries')
    assert job['ssh_password_encrypted'] != payload['ssh_password']
    assert cipher().decrypt(job['ssh_password_encrypted'].encode()).decode() == payload['ssh_password']
    def run(job_id, payload):
        assert payload['password'] == 'super-secret'
        assert payload['job_id'] == str(job['id'])
        from discovery_progress import save_progress
        save_progress(job['id'], {'stage':'neighbors','ip':'192.168.1.1','devices':1,'pending':2,'failed':0})
        current = alice.get('/api/discoveries').json()[0]
        assert current['progress']['stage'] == 'neighbors'
        assert current['started_at'] and current['progress_updated_at']
        assert browser('bob').get('/api/discoveries').json() == []
        return SimpleNamespace(returncode=0,stdout=json.dumps({'snapshot':{'devices':{'SW1':{'reachable':True,'ip':'192.168.1.1','serial_number':'FOC1234ABCD'}},'links':[]},'vlans':{'vlans':[]}}))
    monkeypatch.setattr(worker,'discovery_process',run)
    worker.run_discovery(job)
    assert alice.get('/api/discoveries').json()[0]['status'] == 'completed'
    from discovery_progress import save_progress
    save_progress(job['id'], {'stage':'connecting'})
    assert alice.get('/api/discoveries').json()[0]['progress']['stage'] == 'saving'
    assert browser('amy').get('/api/topology').json()['snapshot']['devices']['SW1']['reachable']
    assert alice.get('/api/topology').json()['snapshot']['devices']['SW1']['serial_number'] == 'FOC1234ABCD'
    assert browser('bob').get('/api/topology').json() is None
    assert alice.get('/api/dashboard').json()['counts']['devices'] == 1


def test_analysis_uses_org_topology_exports_and_sends_once(browser,db_env,monkeypatch):
    admin=browser()
    admin.patch('/api/settings',json={'notify_enabled':True})
    result=ingest(admin)
    job=worker.claim('reports')
    assert worker.claim('reports') is None
    captured=[]
    async def generated(job,prompt):
        assert 'Interface Gi1/0/1 link down' in prompt
        return '**สาเหตุ:** พอร์ตขาดการเชื่อมต่อ\nตรวจสอบสายสัญญาณ'
    monkeypatch.setattr(worker,'guarded_analysis',generated)
    monkeypatch.setattr(worker,'send_teams',lambda output:captured.append(output))
    worker.analyze(job)
    alice=browser('alice')
    report=alice.get('/api/reports').json()['items'][0]
    assert report['status']=='completed' and report['notification_status']=='sent'
    assert len(captured)==1
    for format in ('md','json','csv'):
        exported=alice.get(f"/api/reports/{result.json()['id']}/export?format={format}")
        assert exported.status_code==200
        assert 'attachment;' in exported.headers['content-disposition']
        assert 'พอร์ต' in exported.text
    assert browser('bob').get(f"/api/reports/{report['id']}/export").status_code==403
    counts=alice.get('/api/dashboard').json()['counts']
    assert counts['analyzed']==1 and counts['sent']==1


def test_off_switch_suppresses_claimed_and_queued_jobs(browser,monkeypatch):
    admin=browser()
    admin.patch('/api/settings',json={'notify_enabled':True})
    ingest(admin)
    claimed=worker.claim('reports')
    ingest(admin,event='incident-2')
    admin.patch('/api/settings',json={'notify_enabled':False})
    monkeypatch.setattr(worker,'send_teams',lambda _: (_ for _ in ()).throw(AssertionError('must not send')))
    worker.analyze(claimed)
    assert worker.claim('reports') is None
    reports=browser('alice').get('/api/reports').json()['items']
    assert all(r['status']=='suppressed' for r in reports)
    admin.patch('/api/settings',json={'notify_enabled':True})
    assert worker.claim('reports') is None


def test_off_after_generation_prevents_delivery(browser,monkeypatch):
    admin=browser()
    admin.patch('/api/settings',json={'notify_enabled':True})
    ingest(admin)
    job=worker.claim('reports')
    async def generated(job,prompt):
        admin.patch('/api/settings',json={'notify_enabled':False})
        return 'analysis completed just as admin turned off'
    monkeypatch.setattr(worker,'guarded_analysis',generated)
    monkeypatch.setattr(worker,'send_teams',lambda _: (_ for _ in ()).throw(AssertionError('must not send')))
    worker.analyze(job)
    report=browser('alice').get('/api/reports').json()['items'][0]
    assert report['status']=='suppressed' and report['notification_status']=='suppressed'


def test_teams_failure_preserves_analysis(browser,monkeypatch):
    admin=browser();admin.patch('/api/settings',json={'notify_enabled':True});ingest(admin)
    async def generated(job,prompt): return 'valid RCA'
    def send(output): raise RuntimeError('private webhook secret')
    monkeypatch.setattr(worker,'guarded_analysis',generated)
    monkeypatch.setattr(worker,'send_teams',send)
    worker.analyze(worker.claim('reports'))
    report=browser('alice').get('/api/reports').json()['items'][0]
    assert report['output']=='valid RCA' and report['notification_status']=='failed'
    assert 'private webhook secret' not in report['error']


def test_cancels_inflight_ollama_request(browser,monkeypatch):
    admin=browser();admin.patch('/api/settings',json={'notify_enabled':True});ingest(admin)
    job=worker.claim('reports')
    cancelled=[]
    async def slow(job,prompt):
        try:
            admin.patch('/api/settings',json={'notify_enabled':False})
            await asyncio.sleep(10)
        finally: cancelled.append(True)
    monkeypatch.setattr(worker,'ollama_output',slow)
    import pytest
    with pytest.raises(worker.Suppressed): asyncio.run(worker.guarded_analysis(job,'test'))
    assert cancelled==[True]


def test_admin_create_client_and_employee(browser):
    admin=browser()
    created=admin.post('/api/clients',json={'name':'New client'})
    assert created.status_code==201
    client=created.json()
    assert client['webhook_key'] not in admin.get('/api/clients').text
    response=admin.post('/api/users',json={'name':'New employee','email':'new@example.test','password':'new-password-123','role':'Employee','client_id':client['id']})
    assert response.status_code==201
    assert 'password' not in response.text
    assert admin.post('/api/users',json={'name':'Missing org','email':'missing@example.test','password':'new-password-123','role':'Employee'}).status_code==422


def test_password_reset_revokes_sessions_and_checks_role(browser,db_env):
    admin, alice = browser(), browser('alice')
    endpoint=f"/api/users/{db_env['alice']}/password"
    assert alice.post(endpoint,json={'password':'replacement-password'}).status_code == 403
    assert admin.post(endpoint,json={'password':'short'}).status_code == 422
    assert admin.post(endpoint,json={'password':'replacement-password'}).status_code == 200
    assert alice.get('/api/auth/me').status_code == 401
    assert alice.post('/api/auth/login',json={'email':'alice@example.test','password':'replacement-password'}).status_code == 200
