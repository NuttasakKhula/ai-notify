#!/usr/bin/env python3
"""
discover_topology.py
--------------------
Tier 3 - one-off network topology discovery.

Run it once, get topology_snapshot.json. Run it again by hand whenever the
physical network actually changes. There is no polling loop, no scheduler
and no background thread in this tool by design.

In addition to the topology snapshot, the crawler collects the VLAN table
(VLAN ID + VLAN name) from every device it logs into and writes a single
deduplicated list to vlan.json - each VLAN ID appears exactly once across
the whole fleet.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from netmiko import ConnectHandler, SSHDetect
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from cache_topology import topology_cache
from credentials import Credential, load_credentials
from net_drivers import (
    canonical_hostname,
    get_profile,
    normalize_interface,
    parse_cdp_detail_raw,
    parse_lldp_detail_raw,
    parse_snmp_metadata,
    parse_textfsm_neighbors,
    parse_vlan_interface_ips,
    parse_inventory_system_serial,
    source_ip_for_neighbor,
    vendor_of,
    vlan_from_ip,
)

log = logging.getLogger("discovery")


# ===========================================================================
# Connection layer
# ===========================================================================
class DeviceSession:
    """A netmiko session plus the vendor profile that matches the platform."""

    def __init__(self, conn, device_type: str, credential: Credential, ip: str):
        self.conn = conn
        self.device_type = device_type
        self.profile = get_profile(device_type)
        self.credential = credential
        self.ip = ip

    def run(self, command: str, use_textfsm: bool = False):
        """Send a command, swallowing per-command failures (not fatal to BFS)."""
        try:
            return self.conn.send_command(
                command, use_textfsm=use_textfsm, read_timeout=60
            )
        except Exception as e:
            log.debug("%s: command failed '%s': %s", self.ip, command, e)
            return [] if use_textfsm else ""

    def close(self) -> None:
        try:
            self.conn.disconnect()
        except Exception:
            pass


def detect_device_type(ip: str, credential: Credential, timeout: int) -> str:
    """
    Use netmiko's SSHDetect to identify the vendor OS. Falls back to cisco_ios.
    """
    try:
        guesser = SSHDetect(
            device_type="autodetect",
            host=ip,
            conn_timeout=timeout,
            **credential.as_netmiko_kwargs(),
        )
        best = guesser.autodetect()
        guesser.connection.disconnect()
        if best:
            log.debug("%s: autodetected as %s", ip, best)
            return best
    except NetmikoAuthenticationException:
        raise
    except Exception as e:
        log.debug("%s: autodetect failed (%s)", ip, e)
    return "cisco_ios"


def connect(
    ip: str,
    credentials: List[Credential],
    timeout: int,
    preferred_index: int = 0,
) -> Tuple[Optional[DeviceSession], Optional[int], str]:
    """
    Try each credential set in order until one authenticates.
    """
    order = list(range(len(credentials)))
    if 0 <= preferred_index < len(order):
        order.insert(0, order.pop(preferred_index))

    last_error = "unreachable"
    device_type: Optional[str] = None

    for idx in order:
        cred = credentials[idx]
        try:
            if device_type is None:
                device_type = detect_device_type(ip, cred, timeout)

            conn = ConnectHandler(
                device_type=device_type,
                host=ip,
                conn_timeout=timeout,
                fast_cli=False,
                ssh_config_file="./custom_ssh_config",
                **cred.as_netmiko_kwargs(),
            )

            try:
                if not conn.check_enable_mode():
                    conn.enable()
            except Exception:
                pass

            log.info("%s: connected as %s (%s)", ip, cred, device_type)
            return DeviceSession(conn, device_type, cred, ip), idx, ""

        except NetmikoAuthenticationException:
            last_error = "authentication failed"
            log.debug("%s: auth failed with %s, trying next credential", ip, cred)
            device_type = None
            continue
        except NetmikoTimeoutException:
            return None, None, "ssh timeout / unreachable"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            log.debug("%s: connect error with %s: %s", ip, cred, e)
            continue

    return None, None, last_error


# ===========================================================================
# VLAN collection
# ===========================================================================
VLAN_CMD_FALLBACKS: Tuple[Tuple[str, List[str]], ...] = (
    ("juniper", ["show vlans brief", "show vlans"]),
    ("huawei", ["display vlan brief", "display vlan"]),
    ("hp_comware", ["display vlan brief"]),
    ("hp_procurve", ["show vlans"]),
    ("aruba", ["show vlan"]),
    ("arista", ["show vlan"]),
    ("cisco_nxos", ["show vlan brief", "show vlan"]),
    ("cisco_xr", []),
    ("cisco", ["show vlan brief", "show vlan"]),
    ("dell", ["show vlan"]),
    ("extreme", ["show vlan"]),
)
DEFAULT_VLAN_CMDS: List[str] = ["show vlan brief", "show vlan"]

VLAN_ID_MIN = 1
VLAN_ID_MAX = 4094

_VLAN_ID_FIRST_RE = re.compile(r"^\s*(\d{1,4})\s+(\S+)")
_VLAN_NAME_FIRST_RE = re.compile(r"^\s*(?:\S+\s+)?([A-Za-z][\w\-\.]*)\s+(\d{1,4})\s*$")

_VLAN_STOP_MARKERS = (
    "vlan type",
    "primary secondary",
    "remote span vlan",
    "vlan aftype",
)
_VLAN_SKIP_TOKENS = ("vlan name", "vlan id", "----", "====", "vlan trunk")


def vlan_commands_for(session: "DeviceSession") -> List[str]:
    profile_cmds = session.profile.get("vlan_cmds")
    if profile_cmds is not None:
        return list(profile_cmds)

    dtype = (session.device_type or "").lower()
    for prefix, cmds in VLAN_CMD_FALLBACKS:
        if dtype.startswith(prefix) or prefix in dtype:
            return list(cmds)
    return list(DEFAULT_VLAN_CMDS)


def parse_textfsm_vlans(rows: List[dict]) -> List[dict]:
    out: List[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lowered = {str(k).lower(): v for k, v in row.items()}

        raw_id = (
            lowered.get("vlan_id")
            or lowered.get("vlanid")
            or lowered.get("vlan")
            or lowered.get("tag")
            or lowered.get("id")
        )
        raw_name = (
            lowered.get("vlan_name")
            or lowered.get("name")
            or lowered.get("vlanname")
            or ""
        )
        if isinstance(raw_id, list):
            raw_id = raw_id[0] if raw_id else ""
        if isinstance(raw_name, list):
            raw_name = raw_name[0] if raw_name else ""

        vid = _coerce_vlan_id(raw_id)
        if vid is None:
            continue
        out.append({"vlan_id": vid, "vlan_name": str(raw_name).strip()[:64]})
    return out


def parse_vlan_output_raw(output: str) -> List[dict]:
    results: List[dict] = []
    if not output:
        return results

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        low = stripped.lower()
        if any(marker in low for marker in _VLAN_STOP_MARKERS):
            break
        if any(tok in low for tok in _VLAN_SKIP_TOKENS):
            continue
        if stripped[0] in "-=*":
            continue
        if line[:1].isspace() and not stripped[0].isdigit():
            m = _VLAN_NAME_FIRST_RE.match(stripped)
            if not m:
                continue
            vid = _coerce_vlan_id(m.group(2))
            if vid is not None:
                results.append({"vlan_id": vid, "vlan_name": m.group(1)[:64]})
            continue

        m = _VLAN_ID_FIRST_RE.match(stripped)
        if m:
            vid = _coerce_vlan_id(m.group(1))
            name = m.group(2)
            if vid is not None and not name.isdigit():
                results.append({"vlan_id": vid, "vlan_name": name[:64]})
            continue

        m = _VLAN_NAME_FIRST_RE.match(stripped)
        if m:
            vid = _coerce_vlan_id(m.group(2))
            if vid is not None:
                results.append({"vlan_id": vid, "vlan_name": m.group(1)[:64]})

    return results


def _coerce_vlan_id(value) -> Optional[int]:
    try:
        vid = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if VLAN_ID_MIN <= vid <= VLAN_ID_MAX:
        return vid
    return None


def gather_vlans(session: DeviceSession) -> List[dict]:
    commands = vlan_commands_for(session)
    if not commands:
        log.debug("%s: no VLAN command for %s", session.ip, session.device_type)
        return []

    found: List[dict] = []
    for cmd in commands:
        parsed = session.run(cmd, use_textfsm=True)

        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            found = parse_textfsm_vlans(parsed)
        else:
            raw = parsed if isinstance(parsed, str) else session.run(cmd)
            found = parse_vlan_output_raw(raw)

        if found:
            log.debug("%s: %d VLAN(s) from '%s'", session.ip, len(found), cmd)
            break

    per_device: Dict[int, dict] = {}
    for entry in found:
        vid = entry["vlan_id"]
        existing = per_device.get(vid)
        if existing is None:
            per_device[vid] = entry
        elif not existing["vlan_name"] and entry["vlan_name"]:
            per_device[vid] = entry

    return [per_device[vid] for vid in sorted(per_device)]


# ===========================================================================
# Fact gathering
# ===========================================================================
def gather_facts(session: DeviceSession) -> dict:
    hostname_raw = ""
    try:
        hostname_raw = session.conn.find_prompt().strip().rstrip("#>$]").lstrip("<[")
    except Exception:
        pass

    facts = {
        "hostname": canonical_hostname(hostname_raw) or canonical_hostname(session.ip),
        "hostname_raw": hostname_raw,
        "ip": session.ip,
        "vlan": vlan_from_ip(session.ip) or "",
        "vendor": vendor_of(session.device_type),
        "device_type": session.device_type,
        "platform": "",
        "os_version": "",
        "serial_number": "",
        "snmp_location": "",
        "snmp_contact": "",
        "credential_used": session.credential.label,
        "reachable": True,
        "crawled": True,
    }

    # Keep the SSH address on the device and use verified SVI addresses on links.
    if facts["vendor"] == "cisco":
        output = session.run("sh version | include  System serial number")
        serial = re.search(
            r"^[ \t]*System[ \t]+serial[ \t]+number[ \t]*:[ \t]*([^\s:]+)[ \t]*\r?$",
            output if isinstance(output, str) else "",
            re.MULTILINE | re.IGNORECASE,
        )
        if serial:
            facts["serial_number"] = serial.group(1)
        else:
            inventory = session.run("show inventory")
            facts["serial_number"] = parse_inventory_system_serial(
                inventory if isinstance(inventory, str) else ""
            )
        output = session.run("show ip interface brief")
        facts["vlan_ips"] = parse_vlan_interface_ips(
            output if isinstance(output, str) else ""
        )

    for cmd in session.profile.get("version_cmds", []):
        parsed = session.run(cmd, use_textfsm=True)
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            row = parsed[0]
            hw = row.get("hardware") or row.get("platform") or ""
            if isinstance(hw, list):
                hw = hw[0] if hw else ""
            facts["platform"] = str(hw)[:200]
            facts["os_version"] = str(row.get("version", ""))[:200]
            break
        if isinstance(parsed, str) and parsed.strip():
            facts["os_version"] = parsed.strip().splitlines()[0][:200]
            break

    for cmd in session.profile.get("snmp_cmds", []):
        output = session.run(cmd)
        meta = parse_snmp_metadata(output if isinstance(output, str) else "")
        if meta["snmp_location"] or meta["snmp_contact"]:
            facts.update(meta)
            break

    return facts


def gather_neighbors(session: DeviceSession) -> List[dict]:
    neighbors: List[dict] = []

    for protocol, cmds in (
        ("cdp", session.profile.get("cdp_cmds", [])),
        ("lldp", session.profile.get("lldp_cmds", [])),
    ):
        for cmd in cmds:
            parsed = session.run(cmd, use_textfsm=True)

            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                found = parse_textfsm_neighbors(parsed, protocol)
            else:
                raw = parsed if isinstance(parsed, str) else session.run(cmd)
                found = (
                    parse_cdp_detail_raw(raw)
                    if protocol == "cdp"
                    else parse_lldp_detail_raw(raw)
                )

            if found:
                neighbors.extend(found)
                break

    merged: Dict[tuple, dict] = {}
    for n in neighbors:
        key = (n["local_port"], n["remote_hostname"], n["remote_port"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = n
        elif not existing.get("remote_ip") and n.get("remote_ip"):
            merged[key] = n

    return list(merged.values())


# ===========================================================================
# BFS crawler
# ===========================================================================
class TopologyDiscovery:
    def __init__(
        self,
        credentials: List[Credential],
        max_depth: int = 5,
        timeout: int = 15,
        exclude: Optional[List[str]] = None,
        collect_vlans: bool = True,
        on_progress=None,
    ):
        self.credentials = credentials
        self.max_depth = max_depth
        self.timeout = timeout
        self.exclude = {canonical_hostname(x) for x in (exclude or []) if x}
        self.collect_vlans = collect_vlans
        self.on_progress = on_progress

        self.devices: Dict[str, dict] = {}
        self.links: List[dict] = []
        self.failures: List[dict] = []

        self.vlans: Dict[int, dict] = {}

        self.visited_hosts: set[str] = set()
        self.visited_ips: set[str] = set()
        self._link_keys: set[frozenset] = set()
        self._preferred_cred = 0

    def run(self, seed_ips: List[str]) -> dict:
        started = time.time()
        queue: deque[Tuple[str, str, int]] = deque()

        for ip in seed_ips:
            if ip not in self.visited_ips:
                queue.append((ip, "", 0))
                self.visited_ips.add(ip)

        while queue:
            ip, hint_name, depth = queue.popleft()

            def progress(stage):
                if self.on_progress:
                    self.on_progress({'stage': stage, 'ip': ip, 'depth': depth,
                                      'devices': len(self.visited_hosts),
                                      'failed': len(self.failures), 'pending': len(queue)})

            progress('connecting')

            log.info(
                "[depth %d] visiting %s %s",
                depth,
                ip,
                f"({hint_name})" if hint_name else "",
            )
            session, cred_idx, error = connect(
                ip, self.credentials, self.timeout, self._preferred_cred
            )

            if session is None:
                self._record_failure(ip, hint_name, depth, error)
                progress('unreachable')
                continue

            if cred_idx is not None:
                self._preferred_cred = cred_idx

            try:
                progress('facts')
                facts = gather_facts(session)
                hostname = facts["hostname"]

                if hostname in self.visited_hosts:
                    log.info("%s: already visited as %s, skipping", ip, hostname)
                    continue

                self.visited_hosts.add(hostname)
                facts["depth"] = depth
                self.devices[hostname] = facts

                progress('neighbors')
                neighbors = gather_neighbors(session)
                facts["neighbor_count"] = len(neighbors)
                log.info("%s (%s): %d neighbor(s)", hostname, ip, len(neighbors))

                # 📌 📌 จุดที่หายไป! พี่ซองชานเติมโค้ดเก็บ VLAN กลับเข้ามาให้แล้วครับ
                if self.collect_vlans:
                    progress('vlans')
                    device_vlans = gather_vlans(session)
                    new_count = self._merge_vlans(hostname, device_vlans)
                    facts["vlan_count"] = len(device_vlans)
                    log.info(
                        "%s (%s): %d vlan(s), %d new",
                        hostname, ip, len(device_vlans), new_count
                    )

            finally:
                session.close()

            for nb in neighbors:
                self._add_link(hostname, facts, nb)
                self._enqueue_neighbor(queue, nb, depth)
            progress('device_done')

        return self._build_snapshot(seed_ips, time.time() - started)

    def _enqueue_neighbor(self, queue: deque, nb: dict, depth: int) -> None:
        remote_host = nb["remote_hostname"]
        remote_ip = nb.get("remote_ip", "")

        if depth + 1 > self.max_depth:
            return
        if not remote_ip:
            return
        if remote_host in self.visited_hosts or remote_host in self.exclude:
            return
        if remote_ip in self.visited_ips:
            return

        platform = (nb.get("remote_platform") or "").lower()
        if any(tag in platform for tag in ("ip phone", "cisco ip", "webcam", "printer")):
            return

        self.visited_ips.add(remote_ip)
        queue.append((remote_ip, remote_host, depth + 1))

    def _merge_vlans(self, hostname: str, device_vlans: List[dict]) -> int:
        new_count = 0
        for entry in device_vlans:
            vid = entry["vlan_id"]
            name = entry.get("vlan_name", "")
            existing = self.vlans.get(vid)

            if existing is None:
                self.vlans[vid] = {
                    "vlan_id": vid,
                    "vlan_name": name,
                    "devices": [hostname],
                    "device_names": {hostname: name},
                }
                new_count += 1
                continue

            if hostname not in existing["devices"]:
                existing["devices"].append(hostname)
            existing["device_names"][hostname] = name

            if not existing["vlan_name"] and name:
                existing["vlan_name"] = name
            elif name and name != existing["vlan_name"]:
                log.debug(
                    "VLAN %d name mismatch: keeping '%s', %s reports '%s'",
                    vid,
                    existing["vlan_name"],
                    hostname,
                    name,
                )
        return new_count

    def build_vlan_export(self) -> dict:
        return {
            "meta": {
                "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
                "vlan_count": len(self.vlans),
                "source_device_count": sum(
                    1 for d in self.devices.values() if d.get("crawled")
                ),
                "generator": "discover_topology.py (VLAN export)",
                "schema_version": 1,
            },
            "vlans": [self.vlans[vid] for vid in sorted(self.vlans)],
        }

    def _add_link(self, local_host: str, facts: dict, nb: dict) -> None:
        key = frozenset(
            {
                (local_host, nb["local_port"]),
                (nb["remote_hostname"], nb["remote_port"]),
            }
        )
        if key in self._link_keys:
            return
        self._link_keys.add(key)

        discovery_ip = facts["ip"]
        source_ip = source_ip_for_neighbor(
            discovery_ip, nb.get("remote_ip", ""), facts.get("vlan_ips", {})
        )

        self.links.append(
            {
                "source_device": local_host,
                "source_ip": source_ip,
                "source_discovery_ip": discovery_ip,
                "source_port": nb["local_port"],
                "target_device": nb["remote_hostname"],
                "target_ip": nb.get("remote_ip", ""),
                "target_port": nb["remote_port"],
                "target_vlan": vlan_from_ip(nb.get("remote_ip")) or "",
                "target_platform": nb.get("remote_platform", ""),
                "discovery_protocol": nb.get("protocol", ""),
            }
        )

    def _record_failure(self, ip: str, hostname: str, depth: int, error: str) -> None:
        log.warning("%s: unreachable (%s)", ip, error)
        self.failures.append(
            {"ip": ip, "hostname": hostname, "depth": depth, "error": error}
        )

    def _register_leaf_nodes(self) -> None:
        for link in self.links:
            host = link["target_device"]
            if not host or host in self.devices:
                continue
            self.devices[host] = {
                "hostname": host,
                "ip": link.get("target_ip", ""),
                "vlan": link.get("target_vlan", ""),
                "platform": link.get("target_platform", ""),
                "vendor": "",
                "os_version": "",
                "snmp_location": "",
                "snmp_contact": "",
                "reachable": False,
                "discovered_via": link.get("discovery_protocol", ""),
                "crawled": False,
                "connected_to": {
                    "device": link["source_device"],
                    "port": link["source_port"],
                },
            }

    def _build_snapshot(self, seed_ips: List[str], duration: float) -> dict:
        self._register_leaf_nodes()

        for link in self.links:
            target = self.devices.get(link["target_device"])
            if target:
                link["target_ip"] = link["target_ip"] or target.get("ip", "")
                link["target_vlan"] = link["target_vlan"] or target.get("vlan", "")
                link["target_location"] = target.get("snmp_location", "")
                link["target_contact"] = target.get("snmp_contact", "")
            source = self.devices.get(link["source_device"])
            if source:
                link["source_vlan"] = vlan_from_ip(link["source_ip"]) or source.get("vlan", "")
                link["source_location"] = source.get("snmp_location", "")
                link["source_contact"] = source.get("snmp_contact", "")

        return {
            "meta": {
                "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
                "seed_devices": seed_ips
            },
            "devices": self.devices,
            "links": self.links,
            "failures": self.failures,
        }


# ===========================================================================
# CLI
# ===========================================================================
def resolve_seed(seed: str) -> str:
    try:
        socket.inet_aton(seed)
        return seed
    except OSError:
        pass
    try:
        return socket.gethostbyname(seed)
    except socket.gaierror as e:
        raise SystemExit(f"Cannot resolve seed device '{seed}': {e}")


def parse_args(argv=None) -> argparse.Namespace:
    load_dotenv(override=False)

    p = argparse.ArgumentParser(
        description="One-off BFS network discovery -> topology_snapshot.json + vlan.json"
    )
    p.add_argument(
        "--seeds",
        nargs="+",
        required=True,
        help="Seed device IPs or hostnames (e.g., 192.0.2.10 192.0.2.11)",
    )
    p.add_argument(
        "--max-depth",
        type=int,
        default=int(os.getenv("MAX_DEPTH", "5")),
        help="Maximum BFS hops from the seed (default: 5)",
    )
    p.add_argument(
        "--output",
        default=os.getenv("TOPOLOGY_OUTPUT", "topology_snapshot.json"),
        help="Output JSON path (default: topology_snapshot.json)",
    )
    p.add_argument(
        "--vlan-output",
        default=os.getenv("VLAN_OUTPUT", "vlan.json"),
        help="Deduplicated VLAN export path (default: vlan.json)",
    )
    p.add_argument(
        "--no-vlans",
        action="store_true",
        help="Skip VLAN collection and do not write the VLAN export",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("SSH_TIMEOUT", "15")),
        help="SSH connect timeout in seconds (default: 15)",
    )
    p.add_argument(
        "--exclude",
        default=os.getenv("EXCLUDE_DEVICES", ""),
        help="Comma-separated hostnames to never crawl",
    )
    p.add_argument("--env-file", default=None, help="Path to .env (default: ./.env)")
    p.add_argument(
        "--no-cache-push",
        action="store_true",
        help="Write the JSON only; do not push into the RAM/Redis cache",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    args = p.parse_args(argv)
    return args


def main(argv=None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    logging.getLogger("netmiko").setLevel(logging.WARNING)

    credentials = load_credentials(args.env_file)

    seed_ips = [resolve_seed(seed) for seed in args.seeds]

    log.info("=" * 60)
    log.info("Tier 3 topology discovery (Unified Graph)")
    log.info("Seeds: %s | max depth: %d", ", ".join(seed_ips), args.max_depth)
    log.info("=" * 60)

    crawler = TopologyDiscovery(
        credentials=credentials,
        max_depth=args.max_depth,
        timeout=args.timeout,
        exclude=[x.strip() for x in args.exclude.split(",") if x.strip()],
        collect_vlans=not args.no_vlans,
    )

    snapshot = crawler.run(seed_ips)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    if not args.no_vlans:
        vlan_export = crawler.build_vlan_export()
        with open(args.vlan_output, "w", encoding="utf-8") as f:
            json.dump(vlan_export, f, indent=2, ensure_ascii=False)
        log.info(
            "Saved: %s (%d unique VLAN%s)",
            os.path.abspath(args.vlan_output),
            vlan_export["meta"]["vlan_count"],
            "" if vlan_export["meta"]["vlan_count"] == 1 else "s",
        )

    if not args.no_cache_push:
        try:
            topology_cache.load_snapshot(snapshot)
            log.info("Snapshot pushed to %s cache", topology_cache.backend)
        except Exception as e:
            log.warning("Could not push to cache: %s", e)

    has_reachable = any(d.get("reachable") for d in snapshot["devices"].values())

    log.info("-" * 60)
    log.info("Saved: %s", os.path.abspath(args.output))
    log.info("-" * 60)

    return 0 if has_reachable else 1


if __name__ == "__main__":
    sys.exit(main())
