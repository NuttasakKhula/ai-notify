from uuid import uuid4
from db import database


def test_admin_can_add_remove_user_and_revoke_access(browser, db_env):
    admin = browser()
    alice = browser('alice')
    created = admin.post('/api/users', json={'name':'New user','email':'new@example.test','password':'test-password-123','role':'Employee','client_id':str(db_env['org_a'])})
    assert created.status_code == 201
    assert admin.delete('/api/users/'+created.json()['id']).status_code == 200
    assert admin.delete('/api/users/'+str(db_env['alice'])).status_code == 200
    assert alice.get('/api/auth/me').status_code == 401
    assert alice.post('/api/auth/login', json={'email':'alice@example.test','password':'test-password-123'}).status_code == 401
    assert str(db_env['alice']) not in [u['id'] for u in admin.get('/api/users').json()]
    assert next(c for c in admin.get('/api/clients').json() if c['id']==str(db_env['org_a']))['employees'] == 1
    with database() as conn:
        assert conn.execute('SELECT deleted_at FROM users WHERE id=%s', (db_env['alice'],)).fetchone()['deleted_at']
        assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE action='user.deleted'").fetchone()['n'] == 2


def test_user_removal_permissions(browser, db_env):
    employee = browser('alice')
    admin = browser()
    assert employee.delete('/api/users/'+str(db_env['bob'])).status_code == 403
    assert admin.delete('/api/users/'+str(db_env['admin'])).status_code == 409
    assert admin.delete('/api/users/'+str(uuid4())).status_code == 404
    assert admin.delete('/api/users/'+str(db_env['bob'])).status_code == 200
    assert admin.delete('/api/users/'+str(db_env['bob'])).status_code == 404
