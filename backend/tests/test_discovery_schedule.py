import json
import pytest
import worker
from db import database, migrate
from security import cipher

CREDS = [{'username': 'operator', 'password': 'private-secret'}]

@pytest.mark.parametrize('days', [1, 7, 30])
def test_schedule_runs_once_and_keeps_encrypted_inputs(browser, days):
    client = browser('alice')
    job = client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS, 'repeat_days': days}).json()
    schedule = client.get('/api/discovery-schedule').json()
    assert schedule['repeat_days'] == days
    assert 'private-secret' not in str(schedule)
    assert browser('bob').get('/api/discovery-schedule').json() is None
    with database() as conn:
        conn.execute("UPDATE discovery_schedules SET next_run_at=now()-interval '1 day'")
    worker.enqueue_scheduled_discoveries()
    assert len(client.get('/api/discoveries').json()) == 1
    client.post(f"/api/discoveries/{job['id']}/cancel")
    with database() as conn:
        row = conn.execute('SELECT * FROM discoveries WHERE id=%s', (job['id'],)).fetchone()
        assert row['seed_ip'] is None
        assert row['ssh_credentials_encrypted'] is None
        saved = conn.execute('SELECT * FROM discovery_schedules').fetchone()
        assert json.loads(cipher().decrypt(saved['credentials_encrypted'].encode())) == CREDS
    migrate()
    worker.enqueue_scheduled_discoveries()
    worker.enqueue_scheduled_discoveries()
    assert len(client.get('/api/discoveries').json()) == 2
    claimed = worker.claim('discoveries')
    captured = []
    def discover(job_id, payload):
        captured.append(payload)
        raise RuntimeError('Mocked SSH failure')
    from unittest.mock import patch
    with patch.object(worker, 'discovery_process', discover):
        worker.run_discovery(claimed)
    assert captured[0]['credentials'] == CREDS
    assert client.delete('/api/discovery-schedule').status_code == 200
    assert client.get('/api/discovery-schedule').json() is None


def test_forget_and_invalid_intervals(browser, db_env):
    client = browser('alice')
    for days in [0, 2, 31]:
        assert client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS, 'repeat_days': days}).status_code == 422
    job = client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS, 'repeat_days': 7}).json()
    assert browser('bob').delete(f"/api/discovery-schedule?client_id={db_env['org_a']}").status_code == 403
    # A rejected concurrent request must not delete the existing schedule.
    assert client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS}).status_code == 409
    assert client.get('/api/discovery-schedule').json()['repeat_days'] == 7
    client.post(f"/api/discoveries/{job['id']}/cancel")
    assert client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS}).status_code == 202
    assert client.get('/api/discovery-schedule').json() is None
