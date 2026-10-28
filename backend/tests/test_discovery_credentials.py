import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import worker
from db import database, migrate
from security import cipher


CREDS = [{'username': 'core', 'password': 'core-secret'},
         {'username': 'access', 'password': 'access-secret'}]


def test_credentials_encrypted_and_forwarded(browser, monkeypatch):
    client = browser('alice')
    response = client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS})
    assert response.status_code == 202
    job = worker.claim('discoveries')
    assert json.loads(cipher().decrypt(job['ssh_credentials_encrypted'].encode())) == CREDS
    for credential in CREDS:
        assert credential['password'] not in str(job)
        assert credential['password'] not in client.get('/api/discoveries').text
    captured = []
    def discover(job_id, payload):
        captured.append(payload)
        return SimpleNamespace(returncode=0, stdout=json.dumps({'snapshot': {'devices': {'SW1': {'hostname': 'SW1', 'reachable': True}}, 'links': []}, 'vlans': {}}))
    monkeypatch.setattr(worker, 'discovery_process', discover)
    worker.run_discovery(job)
    assert captured[0]['credentials'] == CREDS
    assert client.get('/api/discoveries').json()[0]['status'] == 'completed'
    assert_erased(job['id'])


def assert_erased(job_id):
    with database() as conn:
        row = conn.execute('SELECT ssh_username,ssh_password_encrypted,ssh_credentials_encrypted FROM discoveries WHERE id=%s', (job_id,)).fetchone()
    assert row == {'ssh_username': None, 'ssh_password_encrypted': None, 'ssh_credentials_encrypted': None}


@pytest.mark.parametrize('terminal_status', ['completed', 'failed', 'cancelled'])
def test_status_transition_erases_credentials(browser, terminal_status):
    client = browser('alice')
    job = client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS}).json()
    with database() as conn:
        for status in ('queued', 'running', 'cancelling'):
            row = conn.execute('UPDATE discoveries SET status=%s WHERE id=%s RETURNING ssh_username,ssh_credentials_encrypted', (status, job['id'])).fetchone()
            assert row['ssh_username'] == 'core'
            assert json.loads(cipher().decrypt(row['ssh_credentials_encrypted'].encode())) == CREDS
        conn.execute('UPDATE discoveries SET status=%s WHERE id=%s', (terminal_status, job['id']))
    assert_erased(job['id'])
    assert client.get('/api/discoveries').json()[0]['ssh_username'] is None
    # Even a later update must not reintroduce credentials into finished history.
    with database() as conn:
        conn.execute("UPDATE discoveries SET ssh_username='restored',ssh_password_encrypted='restored',ssh_credentials_encrypted='restored' WHERE id=%s", (job['id'],))
    assert_erased(job['id'])


def test_queued_cancellation_erases_credentials(browser):
    client = browser('alice')
    job = client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS}).json()
    assert client.post(f"/api/discoveries/{job['id']}/cancel").json()['status'] == 'cancelled'
    assert_erased(job['id'])


def test_migration_purges_old_finished_jobs_and_keeps_pending(browser):
    client = browser('alice')
    with database() as conn:
        conn.execute('DROP TRIGGER erase_finished_discovery_credentials ON discoveries')
    finished = []
    for status in ('completed', 'failed', 'cancelled'):
        job = client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS}).json()
        with database() as conn:
            conn.execute('UPDATE discoveries SET status=%s WHERE id=%s', (status, job['id']))
        finished.append(job['id'])
    pending = client.post('/api/discoveries', json={'seed_ip': '192.168.1.1', 'credentials': CREDS}).json()
    migrate()
    for job_id in finished:
        assert_erased(job_id)
    with database() as conn:
        row = conn.execute('SELECT ssh_credentials_encrypted FROM discoveries WHERE id=%s', (pending['id'],)).fetchone()
        assert json.loads(cipher().decrypt(row['ssh_credentials_encrypted'].encode())) == CREDS


@pytest.mark.parametrize('fields', [
    {'credentials': []}, {'credentials': CREDS * 6},
    {'credentials': [{'username': 'core'}]},
    {'credentials': CREDS, 'ssh_username': 'old', 'ssh_password': 'old'}, {},
])
def test_invalid_credentials_rejected(browser, fields):
    response = browser('alice').post('/api/discoveries', json={'seed_ip': '192.168.1.1', **fields})
    assert response.status_code == 422
    assert 'core-secret' not in response.text
    assert 'access-secret' not in response.text


def test_runner_tries_second_account_after_authentication_failure(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'discover-topology'))
    import discover_topology as discovery
    import discovery_runner
    attempts = []
    def detect(ip, credential, timeout):
        attempts.append(credential.username)
        if credential.username == 'core':
            raise discovery.NetmikoAuthenticationException('Rejected')
        return 'cisco_ios'
    monkeypatch.setenv('DISCOVERY_ALLOWED_CIDRS', '192.168.0.0/16')
    monkeypatch.setattr(discovery, 'detect_device_type', detect)
    monkeypatch.setattr(discovery, 'ConnectHandler', lambda **kwargs: SimpleNamespace(check_enable_mode=lambda: True, disconnect=lambda: None))
    monkeypatch.setattr(discovery, 'gather_facts', lambda session: {'hostname': 'SW1', 'ip': '192.168.1.1', 'reachable': True})
    monkeypatch.setattr(discovery, 'gather_neighbors', lambda session: [])
    monkeypatch.setattr(discovery, 'gather_vlans', lambda session: [])
    # Restore the adapter's temporary wrapper after this test.
    monkeypatch.setattr(discovery, 'connect', discovery.connect)
    result = discovery_runner.run({'seed_ip': '192.168.1.1', 'credentials': CREDS, 'max_depth': 0})
    assert attempts == ['core', 'access']
    assert len(result['snapshot']['devices']) == 1
