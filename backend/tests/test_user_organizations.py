from uuid import uuid4
from db import database, migrate


def test_existing_user_can_access_multiple_organizations(browser, db_env):
    admin, alice, bob = browser(), browser('alice'), browser('bob')
    org_a, org_b = str(db_env['org_a']), str(db_env['org_b'])
    endpoint = f"/api/users/{db_env['alice']}/organizations/{org_b}"
    assert alice.get('/api/logs', params={'client_id':org_b}).status_code == 403
    assert admin.put(endpoint).json() == {'ok':True,'added':True}
    assert admin.put(endpoint).json() == {'ok':True,'added':False}
    assert admin.put(f"/api/users/{db_env['alice']}/organizations/{org_a}").json()['added'] is False
    assert {c['id'] for c in alice.get('/api/clients').json()} == {org_a,org_b}
    for org in (org_a, org_b):
        for path in ('logs','reports','topology','dashboard','discoveries'):
            assert alice.get('/api/'+path,params={'client_id':org}).status_code == 200
    assert alice.get('/api/auth/me').json()['client_id'] == org_a
    assert bob.get('/api/logs',params={'client_id':org_a}).status_code == 403
    outsider = admin.post('/api/clients',json={'name':'Outside'}).json()['id']
    for path in ('logs','reports','topology','dashboard','discoveries'):
        assert alice.get('/api/'+path,params={'client_id':outsider}).status_code == 403
    user = next(u for u in admin.get('/api/users').json() if u['id']==str(db_env['alice']))
    assert {c['id'] for c in user['organizations']} == {org_a,org_b}
    counts = {c['id']:c['employees'] for c in admin.get('/api/clients').json()}
    assert counts[org_a] == 2 and counts[org_b] == 2
    migrate()
    assert len(alice.get('/api/clients').json()) == 2
    assert admin.delete('/api/users/'+str(db_env['alice'])).status_code == 200
    assert alice.get('/api/logs',params={'client_id':org_b}).status_code == 401
    counts = {c['id']:c['employees'] for c in admin.get('/api/clients').json()}
    assert counts[org_a] == 1 and counts[org_b] == 1
    with database() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action='user.organization_added'").fetchone()['n'] == 1


def test_membership_grants_require_admin_and_valid_targets(browser, db_env):
    admin, alice = browser(), browser('alice')
    path = f"/api/users/{db_env['alice']}/organizations/{db_env['org_b']}"
    assert alice.put(path).status_code == 403
    assert admin.put(f"/api/users/{uuid4()}/organizations/{db_env['org_b']}").status_code == 404
    assert admin.put(f"/api/users/{db_env['alice']}/organizations/{uuid4()}").status_code == 404
    assert admin.put(f"/api/users/{db_env['admin']}/organizations/{db_env['org_b']}").status_code == 422
    admin.delete('/api/users/'+str(db_env['alice']))
    assert admin.put(path).status_code == 404
