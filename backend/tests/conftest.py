import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from cryptography.fernet import Fernet
from psycopg import sql
from psycopg.conninfo import make_conninfo
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))
from db import database, migrate
from security import password_hash, digest
from api import app


@pytest.fixture
def db_env(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a disposable PostgreSQL database')
    schema = 'test_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    monkeypatch.setenv('DATABASE_URL', make_conninfo(url, options=f'-c search_path={schema}'))
    monkeypatch.setenv('CREDENTIAL_ENCRYPTION_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    monkeypatch.setenv('APP_ORIGIN', 'http://testserver')
    monkeypatch.setenv('DISCOVERY_ALLOWED_CIDRS', '10.0.0.0/8,192.168.0.0/16')
    migrate()
    ids = {key: uuid4() for key in ('org_a', 'org_b', 'admin', 'alice', 'amy', 'bob')}
    with database() as conn:
        for name, key in [('org_a', 'key-a'), ('org_b', 'key-b')]:
            conn.execute('INSERT INTO clients(id,name,webhook_hash) VALUES(%s,%s,%s)', (ids[name], name, digest(key)))
        for name, role, org in [('admin','Admin',None), ('alice','Employee','org_a'), ('amy','Employee','org_a'), ('bob','Employee','org_b')]:
            conn.execute('INSERT INTO users(id,client_id,name,email,role,password_hash) VALUES(%s,%s,%s,%s,%s,%s)',
                         (ids[name], ids.get(org), name, name+'@example.test', role, password_hash('test-password-123')))
    yield ids
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


@pytest.fixture
def browser(db_env):
    clients = []

    def login(name='admin'):
        client = TestClient(app, headers={'X-Requested-With':'ai-notify', 'Origin':'http://testserver'})
        response = client.post('/api/auth/login', json={'email': name+'@example.test', 'password':'test-password-123'})
        assert response.status_code == 200, response.text
        clients.append(client)
        return client

    yield login
    for client in clients:
        client.close()
