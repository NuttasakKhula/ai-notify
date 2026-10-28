import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'discover-topology'))
from discover_topology import DeviceSession, gather_facts
from net_drivers import parse_inventory_system_serial


COMMAND = 'sh version | include  System serial number'


@pytest.mark.parametrize('output,expected', [
    ('System serial number            : FOC1234ABCD\r\n', 'FOC1234ABCD'),
    ('SW1#sh version | include  System serial number\r\n'
     '  System serial number: ABC-123  \r\nSW1#', 'ABC-123'),
    ('SYSTEM SERIAL NUMBER : ABC123\n', 'ABC123'),
    ('System serial number : \r\nSW1#', ''),
    ('Motherboard serial number : WRONG\n', ''),
    ('% Invalid input detected at marker.', ''),
    ('', ''),
    ([], ''),
])
def test_serial_is_collected_without_changing_other_facts(output, expected):
    commands = []
    def send(command, **kwargs):
        commands.append(command)
        return output if command == COMMAND else ''
    session = DeviceSession(
        SimpleNamespace(find_prompt=lambda: 'SW1#', send_command=send),
        'cisco_ios', SimpleNamespace(label='test'), '192.168.1.1',
    )
    facts = gather_facts(session)
    assert facts['serial_number'] == expected
    assert facts['hostname'] == 'SW1'
    assert facts['reachable'] is True
    assert commands.count(COMMAND) == 1
    assert ('show inventory' in commands) == (not expected)


def test_serial_command_failure_does_not_abort_discovery():
    def send(command, **kwargs):
        if command == COMMAND:
            raise TimeoutError('No command response')
        return ''
    session = DeviceSession(
        SimpleNamespace(find_prompt=lambda: 'SW1#', send_command=send),
        'cisco_ios', SimpleNamespace(label='test'), '192.168.1.1',
    )
    assert gather_facts(session)['serial_number'] == ''


def test_cisco_serial_command_is_not_sent_to_other_vendors():
    commands = []
    session = DeviceSession(
        SimpleNamespace(find_prompt=lambda: 'SW1#',
                        send_command=lambda cmd, **kwargs: commands.append(cmd) or ''),
        'juniper_junos', SimpleNamespace(label='test'), '192.168.1.1',
    )
    assert gather_facts(session)['serial_number'] == ''
    assert COMMAND not in commands
    assert 'show inventory' not in commands


INVENTORY = '''NAME: "Switch System", DESCR: "Cisco Systems, Inc. WS-C4948E 1 slot switch "
PID:                   , VID:      , SN: CAT1642S2Z5

NAME: "Supervisor(slot 1)", DESCR: "10/100/1000BaseT Supervisor"
PID: WS-C4948E         , VID: V07  , SN: CAT1642S2Z5

NAME: "Power Supply 1", DESCR: "Power Supply ( AC 300W )"
PID: PWR-C49E-300AC-R  , VID:      , SN: PAC18474MGW

NAME: "Power Supply 2", DESCR: "Power Supply ( AC 300W )"
PID: PWR-C49E-300AC-R  , VID:      , SN: QCS18221P9P
'''


@pytest.mark.parametrize('version_fails', [False, True])
def test_sw5_inventory_fallback(version_fails):
    def send(command, **kwargs):
        if command == COMMAND and version_fails:
            raise TimeoutError('No version response')
        return INVENTORY if command == 'show inventory' else ''
    session = DeviceSession(
        SimpleNamespace(find_prompt=lambda: 'SW5#', send_command=send),
        'cisco_ios', SimpleNamespace(label='test'), '192.168.137.32',
    )
    facts = gather_facts(session)
    assert facts['serial_number'] == 'CAT1642S2Z5'
    assert facts['hostname'] == 'SW5'
    assert facts['reachable'] is True


@pytest.mark.parametrize('output,expected', [
    (INVENTORY.replace('\n', '\r\n'), 'CAT1642S2Z5'),
    ('NAME: "Power Supply 1", DESCR: "PSU"\nPID: PSU, SN: WRONG\n' + INVENTORY, 'CAT1642S2Z5'),
    (INVENTORY.replace('Switch System', 'Chassis'), 'CAT1642S2Z5'),
    (INVENTORY.replace('SN: CAT1642S2Z5', 'SN: '), ''),
    (INVENTORY.replace('SN: CAT1642S2Z5', 'SN: N/A'), ''),
    ('NAME: "Power Supply 1", DESCR: "PSU"\nPID: PSU, SN: WRONG\n', ''),
    ('NAME: "Supervisor(slot 1)", DESCR: "Supervisor"\nPID: SUP, SN: WRONG\n', ''),
    ('% Invalid input detected', ''),
    ('', ''),
])
def test_inventory_selects_only_system_serial(output, expected):
    assert parse_inventory_system_serial(output) == expected
