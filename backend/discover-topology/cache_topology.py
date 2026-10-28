"""
cache_topology.py
-----------------
RAM cache for the static topology snapshot.

Two backends:
  * memory  - a plain Python dict held in the FastAPI process. Fastest,
              zero dependencies. Use this when middleware runs as one process.
  * redis   - shared cache, so multiple uvicorn workers (or a separate
              analyzer process) read the same snapshot without re-reading disk.
              Set TOPOLOGY_CACHE_BACKEND=redis in .env.

The public surface is backwards compatible with the existing middleware.py:
    topology_cache.is_loaded()
    topology_cache.load("topology_snapshot.json")
    topology_cache.get()          -> list of link dicts
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from typing import Any, Dict, List, Optional

log = logging.getLogger("topology.cache")

REDIS_KEY = os.getenv("TOPOLOGY_REDIS_KEY", "tier3:topology:snapshot")


def normalize_device_name(name: Optional[str]) -> str:
    """Same rule as middleware.normalize_device_name / drivers.canonical_hostname."""
    if not name:
        return ""
    return str(name).split("(")[0].split(".")[0].strip().upper()


class TopologyCache:
    """In-RAM topology store with an optional Redis tier behind it."""

    def __init__(self, backend: Optional[str] = None):
        self._snapshot: Dict[str, Any] = {}
        self._links: List[dict] = []
        self._devices: Dict[str, dict] = {}
        self._adjacency: Dict[str, set] = {}
        self._loaded = False

        self.backend = (backend or os.getenv("TOPOLOGY_CACHE_BACKEND", "memory")).lower()
        self._redis = self._connect_redis() if self.backend == "redis" else None

    # -- backend ---------------------------------------------------------
    def _connect_redis(self):
        try:
            import redis  # imported lazily so memory backend needs no redis lib

            client = redis.Redis(
                host=os.getenv("REDIS_HOST", "127.0.0.1"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
                socket_timeout=5,
            )
            client.ping()
            log.info("Redis cache backend connected")
            return client
        except Exception as e:  # fall back rather than break the analyzer
            log.warning("Redis unavailable (%s), falling back to in-memory cache", e)
            self.backend = "memory"
            return None

    # -- loading ---------------------------------------------------------
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self, path: str = "topology_snapshot.json") -> "TopologyCache":
        """
        Populate the cache. Tries Redis first (already warm from a previous
        discovery run), then falls back to the JSON file on disk.
        """
        if self._redis:
            raw = self._redis.get(REDIS_KEY)
            if raw:
                self._ingest(json.loads(raw))
                log.info("Topology loaded from Redis (%d links)", len(self._links))
                return self

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._ingest(data)

        # Warm Redis so other workers skip the disk read.
        if self._redis:
            self._redis.set(REDIS_KEY, json.dumps(self._snapshot, ensure_ascii=False))

        log.info("Topology loaded from %s (%d links)", path, len(self._links))
        return self

    def load_snapshot(self, snapshot: Dict[str, Any]) -> "TopologyCache":
        """Push a freshly discovered snapshot straight into RAM (and Redis)."""
        self._ingest(snapshot)
        if self._redis:
            self._redis.set(REDIS_KEY, json.dumps(self._snapshot, ensure_ascii=False))
        return self

    def _ingest(self, data: Any) -> None:
        """Accept the new snapshot dict or the legacy bare list of links."""
        if isinstance(data, list):
            # Legacy full_topology.json format.
            self._snapshot = {"meta": {}, "devices": {}, "links": data}
        else:
            self._snapshot = data

        self._links = self._snapshot.get("links", [])
        self._devices = self._snapshot.get("devices", {})

        # Build an undirected adjacency index once, so lookups are O(1).
        self._adjacency = {}
        for link in self._links:
            a = normalize_device_name(link.get("source_device"))
            b = normalize_device_name(link.get("target_device"))
            if not a or not b:
                continue
            self._adjacency.setdefault(a, set()).add(b)
            self._adjacency.setdefault(b, set()).add(a)

        self._loaded = True

    # -- reads -----------------------------------------------------------
    def get(self) -> List[dict]:
        """Backwards compatible: middleware expects the flat list of links."""
        return self._links

    def get_snapshot(self) -> Dict[str, Any]:
        return self._snapshot

    def get_device(self, name: str) -> Optional[dict]:
        return self._devices.get(normalize_device_name(name))

    def get_links_for(self, name: str) -> List[dict]:
        """Every link touching this device (1 hop) - same job as
        middleware.get_relevant_topology(), just pre-indexed."""
        target = normalize_device_name(name)
        return [
            link
            for link in self._links
            if target in (
                normalize_device_name(link.get("source_device")),
                normalize_device_name(link.get("target_device")),
            )
        ]

    def blast_radius(self, name: str, depth: int = 1) -> Dict[str, Any]:
        """
        Devices reachable within `depth` hops of the faulty device.
        depth=1 matches the current prompt rule: only directly connected
        devices count as impacted.
        """
        start = normalize_device_name(name)
        seen = {start: 0}
        queue = deque([(start, 0)])

        while queue:
            node, d = queue.popleft()
            if d >= depth:
                continue
            for peer in self._adjacency.get(node, ()):
                if peer not in seen:
                    seen[peer] = d + 1
                    queue.append((peer, d + 1))

        impacted = []
        for host, hops in seen.items():
            if host == start:
                continue
            dev = self._devices.get(host, {})
            impacted.append(
                {
                    "hostname": host,
                    "hops": hops,
                    "ip": dev.get("ip", ""),
                    "vlan": dev.get("vlan", ""),
                    "platform": dev.get("platform", ""),
                    "snmp_location": dev.get("snmp_location", ""),
                    "snmp_contact": dev.get("snmp_contact", ""),
                }
            )
        impacted.sort(key=lambda x: (x["hops"], x["hostname"]))

        return {
            "root_device": start,
            "root_device_info": self._devices.get(start, {}),
            "depth": depth,
            "impacted_devices": impacted,
            "links": self.get_links_for(start),
        }


# Module-level singleton, imported by middleware.py.
topology_cache = TopologyCache()