from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from db import database


def test_delete_organization_removes_data_and_preserves_other_memberships(browser, db_env):
    admin, alice, amy, bob = browser(), browser('alice'), browser('amy'), browser('bob')
    org_a, org_b = db_env['org_a'], db_env['org_b']
    assert admin.put(f"/api/users/{db_env['alice']}/organizations/{org_b}").status_code == 200
    assert admin.put(f"/api/users/{db_env['bob']}/organizations/{org_a}").status_code == 200
    ids = [uuid4() for _ in range(5)]
    with database() as conn:
        conn.execute('UPDATE users SET client_id=%s WHERE id=%s', (org_a, db_env['admin']))
        for org, did in [(org_a, ids[0]), (org_b, ids[1])]:
            conn.execute('''INSERT INTO discoveries(id,client_id,created_by,seed_ip,max_depth,status)
                VALUES(%s,%s,%s,'192.168.1.1',0,'completed')''', (did, org, db_env['amy']))
            conn.execute('INSERT INTO topologies(id,client_id,discovery_id,snapshot,vlans) VALUES(%s,%s,%s,%s,%s)',
                (uuid4(), org, did, Jsonb({'devices': {}}), Jsonb({})))
            original = uuid4()
            conn.execute('INSERT INTO original_logs(id,client_id,payload) VALUES(%s,%s,%s)', (original, org, Jsonb({})))
            conn.execute("INSERT INTO log_history(id,client_id,original_id,device,message,occurred_at) VALUES(%s,%s,%s,'SW','test',now())", (uuid4(), org, original))
            conn.execute("INSERT INTO reports(id,client_id,original_id,device,status,generation) VALUES(%s,%s,%s,'SW','queued',0)", (uuid4(), org, original))
    response = admin.delete(f'/api/clients/{org_a}')
    assert response.status_code == 200, response.text
    assert [c['id'] for c in admin.get('/api/clients').json()] == [str(org_b)]
    assert alice.get('/api/auth/me').json()['client_id'] == str(org_b)
    assert amy.get('/api/auth/me').status_code == 401
    assert bob.get('/api/auth/me').status_code == 200
    assert admin.get('/api/auth/me').json()['client_id'] is None
    assert alice.get(f'/api/topology?client_id={org_a}').status_code == 403
    assert bob.get('/api/topology').status_code == 200
    assert admin.post('/webhook/incident', headers={'X-Webhook-Key':'key-a'}, json={'matches':[]}).status_code == 401
    with database() as conn:
        for table in ('discoveries', 'topologies', 'original_logs', 'log_history', 'reports'):
            assert conn.execute(f'SELECT count(*) AS n FROM {table} WHERE client_id=%s', (org_a,)).fetchone()['n'] == 0
            assert conn.execute(f'SELECT count(*) AS n FROM {table} WHERE client_id=%s', (org_b,)).fetchone()['n'] == 1
        assert conn.execute('SELECT count(*) AS n FROM user_organizations WHERE client_id=%s', (org_a,)).fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) AS n FROM sessions WHERE user_id=%s', (db_env['amy'],)).fetchone()['n'] == 0
        assert conn.execute("SELECT details FROM audit_events WHERE action='client.deleted'").fetchone()['details']['name'] == 'org_a'


@pytest.mark.parametrize('table,status', [('discoveries','running'), ('discoveries','cancelling'), ('reports','running')])
def test_active_jobs_block_deletion_without_changing_users(browser, db_env, table, status):
    admin = browser()
    with database() as conn:
        if table == 'discoveries':
            conn.execute('''INSERT INTO discoveries(id,client_id,created_by,seed_ip,max_depth,status)
                VALUES(%s,%s,%s,'192.168.1.1',0,%s)''', (uuid4(), db_env['org_a'], db_env['alice'], status))
        else:
            original = uuid4()
            conn.execute("INSERT INTO original_logs(id,client_id,payload) VALUES(%s,%s,'{}')", (original, db_env['org_a']))
            conn.execute("INSERT INTO reports(id,client_id,original_id,device,status,generation) VALUES(%s,%s,%s,'SW',%s,0)", (uuid4(), db_env['org_a'], original, status))
    assert admin.delete(f"/api/clients/{db_env['org_a']}").status_code == 409
    assert browser('alice').get('/api/auth/me').status_code == 200
    assert len(admin.get('/api/clients').json()) == 2


def test_delete_permissions_missing_and_queued_discovery(browser, db_env):
    admin, alice = browser(), browser('alice')
    url = f"/api/clients/{db_env['org_a']}"
    assert alice.delete(url).status_code == 403
    assert admin.delete(f'/api/clients/{uuid4()}').status_code == 404
    assert alice.post('/api/discoveries', json={'seed_ip':'192.168.1.1','ssh_username':'test','ssh_password':'test','max_depth':0}).status_code == 202
    assert admin.delete(url).status_code == 200
    assert admin.delete(url).status_code == 404
    assert alice.get('/api/auth/me').status_code == 401
