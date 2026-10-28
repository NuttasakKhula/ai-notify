from pathlib import Path
from types import SimpleNamespace


def test_crawler_emits_real_milestones_and_failures(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'discover-topology'))
    import discover_topology as discovery

    events = []
    closed = []
    session = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(discovery, 'connect', lambda ip, *args: (session, 0, '') if ip.endswith('.1') else (None, None, 'timeout'))
    monkeypatch.setattr(discovery, 'gather_facts', lambda s: {'hostname':'SW1','ip':'192.168.1.1','reachable':True})
    monkeypatch.setattr(discovery, 'gather_neighbors', lambda s: [])
    monkeypatch.setattr(discovery, 'gather_vlans', lambda s: [])
    crawler = discovery.TopologyDiscovery(credentials=[], on_progress=events.append)
    crawler.run(['192.168.1.1', '192.168.1.2'])
    assert [e['stage'] for e in events] == ['connecting','facts','neighbors','vlans','device_done','connecting','unreachable']
    assert events[0]['pending'] == 1
    assert events[-1]['devices'] == 1 and events[-1]['failed'] == 1
    assert closed == [True]
