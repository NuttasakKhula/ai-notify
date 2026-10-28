import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'discover-topology'))

from net_drivers import parse_vlan_interface_ips, source_ip_for_neighbor


class LinkSourceIpTests(unittest.TestCase):
    def test_uses_matching_svi_for_sw2_to_sw1(self):
        output = """Interface              IP-Address      OK? Method Status Protocol
Vlan110                192.168.110.1   YES NVRAM up up
Vlan111                192.168.111.2   YES manual up up
Vlan130                192.168.130.11  YES NVRAM up up
GigabitEthernet1/0/13  unassigned      YES unset up up
"""
        vlan_ips = parse_vlan_interface_ips(output)

        self.assertEqual(
            source_ip_for_neighbor("192.168.111.2", "192.168.130.13", vlan_ips),
            "192.168.130.11",
        )
        self.assertEqual(
            source_ip_for_neighbor("192.168.111.2", "192.168.110.2", vlan_ips),
            "192.168.110.1",
        )

    def test_keeps_discovery_ip_without_verified_svi_match(self):
        self.assertEqual(
            source_ip_for_neighbor(
                "192.168.111.2", "192.168.130.13", {"130": "10.0.130.11"}
            ),
            "192.168.111.2",
        )
        self.assertEqual(
            source_ip_for_neighbor("192.168.111.2", "", {"130": "192.168.130.11"}),
            "192.168.111.2",
        )

    def test_skips_unassigned_and_invalid_addresses(self):
        self.assertEqual(
            parse_vlan_interface_ips(
                "Vlan1 unassigned YES NVRAM down down\n"
                "Vlan130 999.168.130.11 YES NVRAM up up\n"
                "Vlan137 192.168.137.3 YES NVRAM up up\n"
            ),
            {"137": "192.168.137.3"},
        )


@pytest.mark.parametrize('svi_output,expected_ip,expected_vlan', [
    ('Vlan130 192.168.130.11 YES NVRAM up up\n', '192.168.130.11', '130'),
    ('Vlan130 10.0.130.11 YES NVRAM up up\n', '192.168.111.2', '111'),
    ('% Invalid input detected', '192.168.111.2', '111'),
])
def test_web_runner_exports_link_addresses(monkeypatch, svi_output, expected_ip, expected_vlan):
    import discover_topology as discovery
    import discovery_runner

    commands = []
    closed = []

    def run_command(command, **kwargs):
        commands.append(command)
        if command == 'sh version | include  System serial number':
            return 'System serial number : FOC1234ABCD\r\n'
        return svi_output if command == 'show ip interface brief' else ''

    session = SimpleNamespace(
        ip='192.168.111.2', device_type='cisco_ios', profile={},
        credential=SimpleNamespace(label='web'),
        conn=SimpleNamespace(find_prompt=lambda: 'SW2#'),
        run=run_command, close=lambda: closed.append(True),
    )
    monkeypatch.setenv('DISCOVERY_ALLOWED_CIDRS', '192.168.0.0/16')
    monkeypatch.setattr(discovery, 'connect', lambda *args, **kwargs: (session, 0, ''))
    monkeypatch.setattr(discovery, 'gather_neighbors', lambda s: [{
        'local_port': 'GigabitEthernet1/0/13', 'remote_hostname': 'SW1',
        'remote_ip': '192.168.130.13', 'remote_port': 'FastEthernet0/1',
        'protocol': 'cdp',
    }])
    monkeypatch.setattr(discovery, 'gather_vlans', lambda s: [
        {'vlan_id': 130, 'vlan_name': 'management'},
    ])
    events = []
    monkeypatch.setattr(discovery_runner, 'save_progress', lambda job, event: events.append(event))

    result = discovery_runner.run({
        'username': 'test', 'password': 'test', 'seed_ip': session.ip,
        'max_depth': 0, 'job_id': 'test-job',
    })

    link, = result['snapshot']['links']
    assert link['source_ip'] == expected_ip
    assert link['source_vlan'] == expected_vlan
    assert link['source_discovery_ip'] == '192.168.111.2'
    assert link['target_ip'] == '192.168.130.13'
    assert result['snapshot']['devices']['SW2']['ip'] == '192.168.111.2'
    assert result['snapshot']['devices']['SW2']['serial_number'] == 'FOC1234ABCD'
    assert result['vlans']['vlans'][0]['device_names'] == {'SW2': 'management'}
    assert 'show ip interface brief' in commands
    assert events[-1]['stage'] == 'device_done'
    assert closed == [True]


if __name__ == "__main__":
    unittest.main()
