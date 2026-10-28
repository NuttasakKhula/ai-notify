import json
from pathlib import Path


class TopologyCache:
    def __init__(self):
        self._data = None
        self._filepath = None

    def load(self, filepath):
        """โหลด Topology.json เข้า RAM"""
        self._filepath = Path(filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def get(self):
        """คืนข้อมูลจาก RAM"""
        return self._data

    def reload(self):
        """โหลดไฟล์ใหม่"""
        if self._filepath is None:
            raise RuntimeError("Topology file not loaded.")

        self.load(self._filepath)

    def is_loaded(self):
        """เช็คว่ามีข้อมูลใน RAM หรือยัง"""
        return self._data is not None

class VLANCache:
    def __init__(self):
        self._data = None
        self._filepath = None

    def load(self, filepath):
        """โหลด vlan.json เข้า RAM"""
        self._filepath = Path(filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def get(self):
        """คืนข้อมูลจาก RAM"""
        return self._data

    def reload(self):
        """โหลดไฟล์ใหม่"""
        if self._filepath is None:
            raise RuntimeError("VLAN file not loaded.")
        self.load(self._filepath)

    def is_loaded(self):
        """เช็คว่ามีข้อมูลใน RAM หรือยัง"""
        return self._data is not None


topology_cache = TopologyCache()
vlan_cache = VLANCache()