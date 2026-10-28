"""Isolated adapter around the existing crawler; credentials enter on stdin only."""
import ipaddress
import json
import os
import sys
from pathlib import Path
from discovery_progress import save_progress


def allowed_ip(value):
    address = ipaddress.ip_address(value)
    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
        return False
    cidrs = os.getenv('DISCOVERY_ALLOWED_CIDRS', '')
    return any(address in ipaddress.ip_network(cidr.strip()) for cidr in cidrs.split(',') if cidr.strip())


def run(data):
    sys.path.insert(0, str(Path(__file__).parent / 'discover-topology'))
    import discover_topology as discovery
    from credentials import Credential

    original_connect = discovery.connect

    def guarded_connect(ip, *args, **kwargs):
        if not allowed_ip(ip):
            return None, None, 'Address outside configured discovery networks'
        return original_connect(ip, *args, **kwargs)

    discovery.connect = guarded_connect
    crawler = discovery.TopologyDiscovery(
        credentials=[Credential(username=item['username'], password=item['password'], label=f'web-{index + 1}')
                     for index, item in enumerate(data.get('credentials') or [
                         {'username': data['username'], 'password': data['password']}])],
        max_depth=data['max_depth'], timeout=15,
        on_progress=(lambda progress: save_progress(data['job_id'], progress)) if data.get('job_id') else None,
    )
    snapshot = crawler.run([data['seed_ip']])
    return {'snapshot': snapshot, 'vlans': crawler.build_vlan_export()}


if __name__ == '__main__':
    import contextlib
    data = json.load(sys.stdin)
    with contextlib.redirect_stdout(sys.stderr):
        result = run(data)
    json.dump(result, sys.stdout, ensure_ascii=False)
