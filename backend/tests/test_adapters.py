import asyncio
import json

import httpx
import pytest

import worker
from discovery_runner import allowed_ip
from security import password_hash, verify_password


def test_passwords_are_salted_and_verified():
    first = password_hash('example-password')
    assert first != password_hash('example-password')
    assert verify_password('example-password', first)
    assert not verify_password('wrong', first)
    assert not verify_password('anything', 'invalid')


def test_discovery_network_limits_apply_to_neighbors(monkeypatch):
    monkeypatch.setenv('DISCOVERY_ALLOWED_CIDRS','10.0.0.0/8,192.168.0.0/16')
    assert allowed_ip('10.1.2.3')
    assert not allowed_ip('127.0.0.1')
    assert not allowed_ip('169.254.169.254')
    assert not allowed_ip('8.8.8.8')
    assert not allowed_ip('::1')


@pytest.mark.parametrize('chunks,valid', [
    ([{'response':'รายงาน ', 'done':False},{'response':'สำเร็จ','done':True}], True),
    ([{'response':'partial','done':False}], False),
    ([{'response':'','done':True}], False),
    ([{'error':'model unavailable'}],False),
])
def test_ollama_ndjson_contract(monkeypatch,chunks,valid):
    real_client=httpx.AsyncClient
    def transport(request):
        payload=json.loads(request.content)
        assert payload['stream'] is True
        assert payload['prompt']=='input'
        return httpx.Response(200,content='\n'.join(json.dumps(chunk) for chunk in chunks))
    monkeypatch.setattr(worker.httpx,'AsyncClient',lambda **kwargs:real_client(transport=httpx.MockTransport(transport),**kwargs))
    if valid:
        assert asyncio.run(worker.ollama_output({},'input'))=='รายงาน สำเร็จ'
    else:
        with pytest.raises(RuntimeError):asyncio.run(worker.ollama_output({},'input'))


def test_teams_accepts_any_success_status(monkeypatch):
    real_client=httpx.Client
    monkeypatch.setenv('TEAMS_WEBHOOK_URL','https://teams.example.test/hook')
    def transport(request):
        payload=json.loads(request.content)
        assert payload['attachments'][0]['content']['body'][1]['text']=='report'
        return httpx.Response(202)
    monkeypatch.setattr(worker.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(transport),**kwargs))
    worker.send_teams('report')
