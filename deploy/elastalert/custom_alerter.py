"""Copy into ElastAlert's mounted rules directory, not the FastAPI backend."""
import hashlib
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from elastalert.alerts import Alerter
from elastalert.util import EAException

log = logging.getLogger('elastalert')


def json_default(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError('Unsupported match value')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, default=json_default, allow_nan=False)


def device_for(match):
    host = match.get('host') if isinstance(match.get('host'), dict) else {}
    agent = match.get('agent') if isinstance(match.get('agent'), dict) else {}
    return str(match.get('device_name') or match.get('aggregation_key')
               or host.get('name') or agent.get('hostname') or 'UNKNOWN_DEVICE')


class CombinedWebhookAlerter(Alerter):
    required_options = frozenset(['webhook_url', 'webhook_key_file'])

    def alert(self, matches):
        if not matches:
            return
        try:
            key = Path(self.rule['webhook_key_file']).read_text(encoding='utf-8').strip()
        except OSError:
            raise EAException('Cannot read Ai Notify webhook key file') from None
        if not key:
            raise EAException('Ai Notify webhook key file is empty')

        device = device_for(matches[0])
        if any(device_for(match) != device for match in matches):
            raise EAException('Mixed devices in one incident; check aggregation_key')
        if len(matches) > 1000:
            raise EAException('Incident exceeds 1000 matches; reduce aggregation window')

        try:
            payload = {
                'device_name': device, 'aggregation_key': device,
                'matches': matches, 'match_count': len(matches),
            }
            body = canonical(payload).encode('utf-8')
            # ES identities survive serialization and reordering on retry.
            identities = [canonical({'_index': m['_index'], '_id': m['_id']})
                          if m.get('_index') and m.get('_id') else canonical(m)
                          for m in matches]
            identity = canonical({'rule': self.rule['name'], 'device': device,
                                  'matches': sorted(identities)})
        except (TypeError, ValueError):
            raise EAException('Incident contains unsupported JSON values') from None
        if len(body) > 2_000_000:
            raise EAException('Incident exceeds 2 MB; reduce aggregation window')
        event_key = 'ea-' + hashlib.sha256(identity.encode('utf-8')).hexdigest()

        try:
            response = requests.post(
                self.rule['webhook_url'], data=body,
                headers={'Content-Type': 'application/json', 'X-Webhook-Key': key,
                         'Idempotency-Key': event_key},
                timeout=(5, 30), allow_redirects=False,
            )
        except requests.exceptions.RequestException:
            # ElastAlert must record failure so its retry mechanism can act.
            # Raw exceptions can contain URLs, credentials or response content.
            raise EAException('Ai Notify webhook transport failed') from None
        try:
            if response.status_code != 202:
                raise EAException(f'Ai Notify webhook returned HTTP {response.status_code}')
        finally:
            response.close()
        log.info('Ai Notify accepted %d matches; incident=%s', len(matches), event_key)

    def get_info(self):
        return {'type': 'CombinedWebhookAlerter'}
