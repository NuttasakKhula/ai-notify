"""Adapter unit tests; stub only ElastAlert's base class and exception type."""
import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    alerts = types.ModuleType('elastalert.alerts')
    util = types.ModuleType('elastalert.util')

    class Alerter:
        def __init__(self, rule):
            self.rule = rule

    class EAException(Exception):
        pass

    alerts.Alerter = Alerter
    util.EAException = EAException
    monkeypatch.setitem(sys.modules, 'elastalert', types.ModuleType('elastalert'))
    monkeypatch.setitem(sys.modules, 'elastalert.alerts', alerts)
    monkeypatch.setitem(sys.modules, 'elastalert.util', util)
    path = Path(__file__).resolve().parents[2] / 'deploy/elastalert/custom_alerter.py'
    spec = importlib.util.spec_from_file_location('tested_alerter', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    key_file = tmp_path / 'webhook.key'
    key_file.write_text('organization-secret\n', encoding='utf-8')
    alerter = module.CombinedWebhookAlerter({
        'name': 'Network_Device_Alert', 'webhook_url': 'http://ai-notify-api:8000/webhook/incident',
        'webhook_key_file': str(key_file),
    })
    post = Mock(return_value=Mock(status_code=202))
    monkeypatch.setattr(module.requests, 'post', post)
    return alerter, post, EAException, key_file


def event(event_id='1'):
    return {'_index': 'network-logs-2026.09.23', '_id': event_id,
            'device_name': 'SW-CORE-01', 'message': 'Interface down',
            '@timestamp': datetime(2026, 9, 23, tzinfo=timezone.utc)}


def test_contract_and_retry_identity(adapter):
    alerter, post, _, _ = adapter
    matches = [event('1'), event('2')]
    alerter.alert(matches)
    first = post.call_args.kwargs
    body = json.loads(first['data'])
    assert body['device_name'] == 'SW-CORE-01'
    assert body['match_count'] == 2
    assert body['matches'][0]['@timestamp'] == '2026-09-23T00:00:00Z'
    assert first['headers']['X-Webhook-Key'] == 'organization-secret'
    assert first['allow_redirects'] is False
    assert first['timeout'] == (5, 30)
    # Simulate persisted matches reloaded in reverse order after a restart.
    alerter.alert(list(reversed(body['matches'])))
    assert first['headers']['Idempotency-Key'] == post.call_args.kwargs['headers']['Idempotency-Key']
    alerter.alert([event('3')])
    assert first['headers']['Idempotency-Key'] != post.call_args.kwargs['headers']['Idempotency-Key']


@pytest.mark.parametrize('status', [301, 401, 413, 422, 500])
def test_http_failure_is_reported_to_elastalert(adapter, status):
    alerter, post, error, _ = adapter
    post.return_value.status_code = status
    with pytest.raises(error, match=f'HTTP {status}'):
        alerter.alert([event()])
    post.return_value.close.assert_called_once()


def test_timeout_and_secret_not_exposed(adapter, caplog):
    alerter, post, error, _ = adapter
    post.side_effect = requests.Timeout('organization-secret')
    with pytest.raises(error, match='transport failed') as caught:
        alerter.alert([event()])
    assert 'organization-secret' not in str(caught.value) + caplog.text + str(alerter.get_info())


def test_missing_key_fails_without_request(adapter):
    alerter, post, error, key_file = adapter
    key_file.unlink()
    with pytest.raises(error, match='key file'):
        alerter.alert([event()])
    post.assert_not_called()


def test_empty_batch_and_mixed_devices(adapter):
    alerter, post, error, _ = adapter
    alerter.alert([])
    post.assert_not_called()
    with pytest.raises(error, match='Mixed devices'):
        alerter.alert([event(), {**event('2'), 'device_name': 'SW-OTHER'}])
    post.assert_not_called()


def test_fallback_and_rotation(adapter):
    alerter, post, _, key_file = adapter
    match = {'host': {'name': 'SW-CORE-01'}, 'message': 'down', '@timestamp': '2026-09-23T00:00:00Z'}
    alerter.alert([match])
    first_key = post.call_args.kwargs['headers']['Idempotency-Key']
    key_file.write_text('rotated-secret', encoding='utf-8')
    alerter.alert([dict(reversed(list(match.items())))])
    assert post.call_args.kwargs['headers']['Idempotency-Key'] == first_key
    assert post.call_args.kwargs['headers']['X-Webhook-Key'] == 'rotated-secret'
