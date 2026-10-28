"""
net_drivers.py
--------------
Multi-vendor abstraction layer.

Each netmiko device_type maps to a "profile" describing which CLI commands
to run for CDP/LLDP neighbors and SNMP metadata. Parsing is done with
ntc-templates (TextFSM) where available, with regex fallbacks so the crawler
still works on platforms without a template.
"""

from __future__ import annotations

import logging
import ipaddress
import re
from typing import Dict, List, Optional

log = logging.getLogger("discovery.drivers")


def parse_inventory_system_serial(output: str) -> str:
    """Read the system/chassis SN, never a PSU, supervisor or transceiver SN."""
    records = re.split(r'(?im)^[ \t]*NAME[ \t]*:', output)
    for record in records[1:]:
        name = re.match(r'[ \t]*"([^"]+)"', record)
        if not name or name.group(1).strip().casefold() not in {
            'switch system', 'chassis', 'system', 'switch',
        }:
            continue
        serial = re.search(r'(?im)\bSN[ \t]*:[ \t]*([^\s,]+)[ \t]*\r?$', record)
        if serial and serial.group(1).casefold() not in {'n/a', 'na', 'unknown', 'none', '-'}:
            return serial.group(1)
    return ''


# ---------------------------------------------------------------------------
# Vendor profiles
# ---------------------------------------------------------------------------
# cdp/lldp commands are tried in order; the first one that returns usable
# neighbors wins. Empty list = protocol not supported on that platform.
GENERIC_PROFILE = {
    "vendor": "generic",
    "cdp_cmds": [],
    "lldp_cmds": ["show lldp neighbors detail"],
    "snmp_cmds": [],
    "version_cmds": ["show version"],
}

VENDOR_PROFILES: Dict[str, dict] = {
    "cisco_ios": {
        "vendor": "cisco",
        "cdp_cmds": ["show cdp neighbors detail"],
        "lldp_cmds": ["show lldp neighbors detail"],
        "snmp_cmds": ["show running-config | include ^snmp-server (location|contact)"],
        "version_cmds": ["show version"],
    },
    "cisco_xe": {
        "vendor": "cisco",
        "cdp_cmds": ["show cdp neighbors detail"],
        "lldp_cmds": ["show lldp neighbors detail"],
        "snmp_cmds": ["show running-config | include ^snmp-server (location|contact)"],
        "version_cmds": ["show version"],
    },
    "cisco_nxos": {
        "vendor": "cisco",
        "cdp_cmds": ["show cdp neighbors detail"],
        "lldp_cmds": ["show lldp neighbors detail"],
        "snmp_cmds": ["show running-config | include snmp-server.*(location|contact)"],
        "version_cmds": ["show version"],
    },
    "cisco_xr": {
        "vendor": "cisco",
        "cdp_cmds": ["show cdp neighbors detail"],
        "lldp_cmds": ["show lldp neighbors detail"],
        "snmp_cmds": ["show running-config snmp-server | include (location|contact)"],
        "version_cmds": ["show version"],
    },
    "arista_eos": {
        "vendor": "arista",
        "cdp_cmds": [],  # EOS speaks LLDP by default
        "lldp_cmds": ["show lldp neighbors detail"],
        "snmp_cmds": ["show running-config | include snmp-server (location|contact)"],
        "version_cmds": ["show version"],
    },
    "juniper_junos": {
        "vendor": "juniper",
        "cdp_cmds": [],
        "lldp_cmds": ["show lldp neighbors"],
        "snmp_cmds": ["show configuration snmp | display set | match \"location|contact\""],
        "version_cmds": ["show version"],
    },
    "hp_comware": {
        "vendor": "hpe",
        "cdp_cmds": [],
        "lldp_cmds": ["display lldp neighbor-information verbose"],
        "snmp_cmds": ["display current-configuration | include snmp-agent sys-info"],
        "version_cmds": ["display version"],
    },
    "hp_procurve": {
        "vendor": "hpe",
        "cdp_cmds": [],
        "lldp_cmds": ["show lldp info remote-device detail"],
        "snmp_cmds": ["show running-config | include snmp-server (location|contact)"],
        "version_cmds": ["show version"],
    },
    "aruba_os": {
        "vendor": "aruba",
        "cdp_cmds": [],
        "lldp_cmds": ["show lldp neighbors detail"],
        "snmp_cmds": ["show running-config | include snmp-server"],
        "version_cmds": ["show version"],
    },
    "aruba_osswitch": {
        "vendor": "aruba",
        "cdp_cmds": [],
        "lldp_cmds": ["show lldp info remote-device detail"],
        "snmp_cmds": ["show running-config | include snmp-server"],
        "version_cmds": ["show version"],
    },
    "huawei": {
        "vendor": "huawei",
        "cdp_cmds": [],
        "lldp_cmds": ["display lldp neighbor"],
        "snmp_cmds": ["display current-configuration | include snmp-agent sys-info"],
        "version_cmds": ["display version"],
    },
    "huawei_vrpv8": {
        "vendor": "huawei",
        "cdp_cmds": [],
        "lldp_cmds": ["display lldp neighbor"],
        "snmp_cmds": ["display current-configuration | include snmp-agent sys-info"],
        "version_cmds": ["display version"],
    },
    "dell_os10": {
        "vendor": "dell",
        "cdp_cmds": [],
        "lldp_cmds": ["show lldp neighbors detail"],
        "snmp_cmds": ["show running-configuration | grep snmp-server"],
        "version_cmds": ["show version"],
    },
    "fortinet": {
        "vendor": "fortinet",
        "cdp_cmds": [],
        "lldp_cmds": ["get switch lldp neighbors-summary"],
        "snmp_cmds": ["show system snmp sysinfo"],
        "version_cmds": ["get system status"],
    },
    "paloalto_panos": {
        "vendor": "paloalto",
        "cdp_cmds": [],
        "lldp_cmds": ["show lldp neighbors all"],
        "snmp_cmds": [],
        "version_cmds": ["show system info"],
    },
    "mikrotik_routeros": {
        "vendor": "mikrotik",
        "cdp_cmds": [],
        "lldp_cmds": ["/ip neighbor print detail"],
        "snmp_cmds": ["/snmp print"],
        "version_cmds": ["/system resource print"],
    },
}


def get_profile(device_type: str) -> dict:
    """Return the command profile for a netmiko device_type."""
    return VENDOR_PROFILES.get(device_type, GENERIC_PROFILE)


def vendor_of(device_type: str) -> str:
    return get_profile(device_type).get("vendor", "generic")


# ---------------------------------------------------------------------------
# Hostname / interface normalisation
# ---------------------------------------------------------------------------
# CDP often reports "SW-ACCESS-01.corp.local(FDO2043R0KZ)". We want SW-ACCESS-01.
_SERIAL_SUFFIX = re.compile(r"\(([^)]*)\)\s*$")

# Abbreviated -> full interface names, so topology ports match syslog ports.
_IFACE_EXPANSIONS = [
    ("tengigabitethernet", "TenGigabitEthernet"),
    ("gigabitethernet", "GigabitEthernet"),
    ("fastethernet", "FastEthernet"),
    ("twentyfivegige", "TwentyFiveGigE"),
    ("fortygigabitethernet", "FortyGigabitEthernet"),
    ("hundredgige", "HundredGigE"),
    ("port-channel", "Port-channel"),
    ("ethernet", "Ethernet"),
    ("vlan", "Vlan"),
    ("loopback", "Loopback"),
    ("management", "Management"),
    ("mgmteth", "MgmtEth"),
    ("xe-", "xe-"),
    ("ge-", "ge-"),
    ("et-", "et-"),
]

_IFACE_ABBREV = {
    "te": "TenGigabitEthernet",
    "tw": "TwoGigabitEthernet",
    "gi": "GigabitEthernet",
    "gig": "GigabitEthernet",
    "fa": "FastEthernet",
    "fo": "FortyGigabitEthernet",
    "hu": "HundredGigE",
    "po": "Port-channel",
    "eth": "Ethernet",
    "e": "Ethernet",
    "vl": "Vlan",
    "lo": "Loopback",
    "mgmt": "Management",
}


def canonical_hostname(name: Optional[str]) -> str:
    """
    Canonical device key: strip CDP serial suffix, drop the DNS domain,
    uppercase. This is what the BFS 'visited' set is keyed on, and it
    matches normalize_device_name() in middleware.py.
    """
    if not name:
        return ""
    name = _SERIAL_SUFFIX.sub("", str(name)).strip()
    return name.split(".")[0].strip().upper()


def normalize_interface(port: Optional[str]) -> str:
    """Expand abbreviated interface names (Gi1/0/1 -> GigabitEthernet1/0/1)."""
    if not port:
        return ""
    port = str(port).strip()

    lowered = port.lower()
    for prefix, proper in _IFACE_EXPANSIONS:
        if lowered.startswith(prefix):
            return proper + port[len(prefix):]

    # Split "Gi1/0/1" into alpha prefix + the rest.
    m = re.match(r"^([A-Za-z\-]+)(.*)$", port)
    if m:
        alpha, rest = m.group(1).lower(), m.group(2)
        if alpha in _IFACE_ABBREV:
            return _IFACE_ABBREV[alpha] + rest
    return port


def vlan_from_ip(ip: Optional[str]) -> Optional[str]:
    """
    Project convention (see middleware prompt): VLAN id is the 3rd octet,
    i.e. xxx.xxx.VLAN.xxx. Returns None if the IP does not look like IPv4.
    """
    if not ip:
        return None
    m = re.match(r"^\d{1,3}\.\d{1,3}\.(\d{1,3})\.\d{1,3}$", str(ip).strip())
    return m.group(1) if m else None


def parse_vlan_interface_ips(output: str) -> Dict[str, str]:
    """Read Cisco-style Vlan SVI addresses from `show ip interface brief`."""
    vlan_ips: Dict[str, str] = {}
    for line in (output or "").splitlines():
        match = re.match(r"^\s*Vlan(\d+)\s+(\S+)\s+", line, re.I)
        if not match:
            continue
        try:
            vlan_id = int(match.group(1))
            address = str(ipaddress.IPv4Address(match.group(2)))
        except ValueError:
            continue
        if 1 <= vlan_id <= 4094:
            vlan_ips[str(vlan_id)] = address
    return vlan_ips


def source_ip_for_neighbor(
    discovery_ip: str, remote_ip: str, vlan_ips: Dict[str, str]
) -> str:
    """Prefer a local SVI in the remote device's /24; otherwise retain SSH IP.

    This project's address convention uses the third octet as the VLAN ID.
    The /24 check is intentionally conservative because interface brief does
    not include masks, so a VLAN ID match alone is not enough evidence.
    """
    try:
        remote = ipaddress.IPv4Address(remote_ip)
        vlan_id = str(int(str(remote).split(".")[2]))
        candidate = ipaddress.IPv4Address(vlan_ips[vlan_id])
    except (ValueError, KeyError, TypeError):
        return discovery_ip
    if int(remote) >> 8 == int(candidate) >> 8:
        return str(candidate)
    return discovery_ip


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------
def _first(row: dict, *keys: str) -> str:
    """Return the first non-empty value among the given keys (TextFSM key drift)."""
    for k in keys:
        v = row.get(k)
        if isinstance(v, list):
            v = v[0] if v else ""
        if v:
            return str(v).strip()
    return ""


_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _first_ipv4(text: str) -> str:
    m = _IPV4.search(text or "")
    return m.group(0) if m else ""


# ---------------------------------------------------------------------------
# Neighbour parsing
# ---------------------------------------------------------------------------
def parse_textfsm_neighbors(rows: List[dict], protocol: str) -> List[dict]:
    """
    Normalise ntc-templates output (list of dicts) into our neighbour schema.
    Key names differ between template versions and vendors, hence _first().
    """
    neighbors = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        remote_name = _first(
            row,
            "destination_host", "dest_host", "neighbor", "neighbor_name",
            "system_name", "remote_system_name", "chassis_id", "neighbor_sys_name",
        )
        local_port = _first(
            row, "local_port", "local_interface", "local_intf", "interface",
        )
        remote_port = _first(
            row,
            "remote_port", "neighbor_port_id", "neighbor_interface",
            "remote_interface", "port_id", "neighbor_portid",
        )
        mgmt_ip = _first(
            row,
            "management_ip", "mgmt_ip", "management_address", "mgmt_address",
            "neighbor_ip", "ip_address", "management_ip_address", "interface_ip",
        )
        platform = _first(
            row, "platform", "system_description", "neighbor_description",
            "capabilities", "system_capabilities",
        )
        version = _first(row, "software_version", "version", "system_description")

        if not remote_name:
            continue

        neighbors.append(
            {
                "remote_hostname": canonical_hostname(remote_name),
                "remote_hostname_raw": remote_name,
                "local_port": normalize_interface(local_port),
                "remote_port": normalize_interface(remote_port),
                "remote_ip": _first_ipv4(mgmt_ip) or "",
                "remote_platform": platform[:200],
                "remote_os_version": version[:200],
                "protocol": protocol,
            }
        )
    return neighbors


# Cisco "show cdp neighbors detail" blocks are separated by dashed lines.
_CDP_BLOCK_SPLIT = re.compile(r"^-{4,}.*$", re.MULTILINE)


def parse_cdp_detail_raw(output: str) -> List[dict]:
    """Regex fallback for Cisco CDP detail when TextFSM is unavailable."""
    neighbors = []
    for block in _CDP_BLOCK_SPLIT.split(output or ""):
        if "Device ID" not in block:
            continue

        device_id = re.search(r"Device ID\s*:\s*(\S+)", block)
        local_if = re.search(r"Interface\s*:\s*([^,\n]+)", block)
        remote_if = re.search(r"Port ID \(outgoing port\)\s*:\s*([^\n]+)", block)
        platform = re.search(r"Platform\s*:\s*([^,\n]+)", block)
        version = re.search(r"Version\s*:\s*\n?\s*([^\n]+)", block)

        # Prefer the management address block, else the first entry address.
        mgmt = re.search(r"Management address\(es\)\s*:(.*?)(?:\n\s*\n|\Z)", block, re.S)
        ip = _first_ipv4(mgmt.group(1)) if mgmt else ""
        if not ip:
            entry = re.search(r"Entry address\(es\)\s*:(.*?)(?:Platform|\Z)", block, re.S)
            ip = _first_ipv4(entry.group(1)) if entry else ""

        if not device_id:
            continue

        neighbors.append(
            {
                "remote_hostname": canonical_hostname(device_id.group(1)),
                "remote_hostname_raw": device_id.group(1).strip(),
                "local_port": normalize_interface(local_if.group(1) if local_if else ""),
                "remote_port": normalize_interface(remote_if.group(1) if remote_if else ""),
                "remote_ip": ip,
                "remote_platform": platform.group(1).strip() if platform else "",
                "remote_os_version": version.group(1).strip()[:200] if version else "",
                "protocol": "cdp",
            }
        )
    return neighbors


# Generic LLDP verbose output: "Key: value" lines, blocks separated by blanks.
_LLDP_LABELS = {
    "system name": "name",
    "systemname": "name",
    "sysname": "name",
    "device id": "name",
    "chassis id": "chassis",
    "chassisid": "chassis",
    "port id": "remote_port",
    "portid": "remote_port",
    "port description": "remote_port_desc",
    "port id subtype": None,
    "local interface": "local_port",
    "local intf": "local_port",
    "local port id": "local_port",
    "localport": "local_port",
    "interface": "local_port",
    "management address": "ip",
    "management ip address": "ip",
    "mgmt address": "ip",
    "system description": "platform",
    "systemdescription": "platform",
}


def parse_lldp_detail_raw(output: str) -> List[dict]:
    """
    Vendor-agnostic fallback for verbose LLDP output (HPE/Huawei/Aruba/Cisco).
    Splits into blocks on blank lines or dashed separators and reads
    'Label: value' pairs it recognises.
    """
    neighbors: List[dict] = []
    blocks = re.split(r"\n\s*\n|^-{4,}.*$", output or "", flags=re.MULTILINE)

    for block in blocks:
        fields: Dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            label, _, value = line.partition(":")
            key = _LLDP_LABELS.get(label.strip().lower())
            if key and value.strip() and key not in fields:
                fields[key] = value.strip()

        name = fields.get("name") or fields.get("chassis")
        if not name or not fields.get("remote_port"):
            continue

        neighbors.append(
            {
                "remote_hostname": canonical_hostname(name),
                "remote_hostname_raw": name,
                "local_port": normalize_interface(fields.get("local_port", "")),
                "remote_port": normalize_interface(
                    fields.get("remote_port") or fields.get("remote_port_desc", "")
                ),
                "remote_ip": _first_ipv4(fields.get("ip", "")),
                "remote_platform": fields.get("platform", "")[:200],
                "remote_os_version": "",
                "protocol": "lldp",
            }
        )
    return neighbors


# ---------------------------------------------------------------------------
# SNMP metadata parsing
# ---------------------------------------------------------------------------
_SNMP_PATTERNS = [
    # Cisco / Arista / Dell / Aruba
    (re.compile(r"snmp-server\s+location\s+(.+)", re.I), "location"),
    (re.compile(r"snmp-server\s+contact\s+(.+)", re.I), "contact"),
    # HPE Comware / Huawei
    (re.compile(r"snmp-agent\s+sys-info\s+location\s+(.+)", re.I), "location"),
    (re.compile(r"snmp-agent\s+sys-info\s+contact\s+(.+)", re.I), "contact"),
    # Juniper "display set"
    (re.compile(r"set\s+snmp\s+location\s+(.+)", re.I), "location"),
    (re.compile(r"set\s+snmp\s+contact\s+(.+)", re.I), "contact"),
    # Fortinet / generic key-value
    (re.compile(r"^\s*location\s*[:=]\s*(.+)$", re.I | re.M), "location"),
    (re.compile(r"^\s*contact(?:-info)?\s*[:=]\s*(.+)$", re.I | re.M), "contact"),
]


def parse_snmp_metadata(output: str) -> Dict[str, str]:
    """Extract snmp location/contact from raw config output, any vendor."""
    result = {"snmp_location": "", "snmp_contact": ""}
    for pattern, kind in _SNMP_PATTERNS:
        if result[f"snmp_{kind}"]:
            continue
        m = pattern.search(output or "")
        if m:
            result[f"snmp_{kind}"] = m.group(1).strip().strip('"').strip("'")
    return result
