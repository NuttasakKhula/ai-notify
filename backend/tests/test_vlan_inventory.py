from pathlib import Path


def test_vlan_export_preserves_names_per_device(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'discover-topology'))
    from discover_topology import TopologyDiscovery

    crawler = TopologyDiscovery(credentials=[])
    crawler._merge_vlans('SW1', [{'vlan_id': 66, 'vlan_name': 'service-devices-sw1'}])
    crawler._merge_vlans('SW2', [{'vlan_id': 66, 'vlan_name': 'service-devices-sw2'}])
    crawler._merge_vlans('SW2', [{'vlan_id': 66, 'vlan_name': 'service-devices-sw2'}])
    vlan, = crawler.build_vlan_export()['vlans']
    assert vlan['devices'] == ['SW1', 'SW2']
    assert vlan['device_names'] == {'SW1': 'service-devices-sw1', 'SW2': 'service-devices-sw2'}
    assert vlan['vlan_name'] == 'service-devices-sw1'
