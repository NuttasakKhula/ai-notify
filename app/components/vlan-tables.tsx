"use client";

import { useState } from "react";

export type Vlan = {
  vlan_id: number;
  vlan_name: string;
  devices: string[];
  device_names?: Record<string, string>;
};

export function VlanTables({ vlans, chosen, onChoose }: {
  vlans: Vlan[];
  chosen: string;
  onChoose: (device: string) => void;
}) {
  const [search, setSearch] = useState("");
  const term = search.trim().toLowerCase();
  const sorted = [...vlans].sort((a, b) => a.vlan_id - b.vlan_id);
  const visible = sorted.filter((vlan) =>
    `${vlan.vlan_id} ${vlan.vlan_name} ${Object.values(vlan.device_names || {}).join(" ")} ${vlan.devices.join(" ")}`.toLowerCase().includes(term),
  );
  const assignments = sorted.flatMap((vlan) => vlan.devices.map((device) => ({
    vlan, device, name: vlan.device_names?.[device],
  }))).filter(({ vlan, device, name }) =>
    (!chosen || chosen === device) &&
    `${vlan.vlan_id} ${name ?? vlan.vlan_name} ${device}`.toLowerCase().includes(term),
  ).sort((a, b) => a.device.localeCompare(b.device) || a.vlan.vlan_id - b.vlan.vlan_id);

  return <>
    <section className="panel">
      <div className="panel-heading">
        <div><h2>VLAN inventory</h2><p>{vlans.length} VLAN · ข้อมูลจาก discovery ล่าสุด</p></div>
        <input className="compact-input" aria-label="ค้นหา VLAN" placeholder="VLAN ID, ชื่อ หรืออุปกรณ์…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div className="table-scroll vlan-table-scroll" tabIndex={0} role="region" aria-label="VLAN inventory ?????????????"><table>
        <thead><tr><th>VLAN ID</th><th>VLAN Name / Service</th><th>อุปกรณ์ที่พบ VLAN</th></tr></thead>
        <tbody>{visible.map((vlan) => <tr key={vlan.vlan_id}>
          <td className="mono">{vlan.vlan_id}</td>
          <td>{[...new Set([vlan.vlan_name, ...Object.values(vlan.device_names || {})].filter(Boolean))].join(" / ") || "ไม่พบชื่อ VLAN"}</td>
          <td>{vlan.devices.map((device, index) => <span key={device}>{index > 0 && ", "}<button className="text-link" onClick={() => onChoose(device)}>{device}</button></span>)}</td>
        </tr>)}{!visible.length && <tr><td colSpan={3}>{vlans.length ? "ไม่พบ VLAN ที่ตรงกับการค้นหา" : "ยังไม่มีข้อมูล VLAN จาก discovery"}</td></tr>}</tbody>
      </table></div>
    </section>
    <section className="panel">
      <div className="panel-heading">
        <div><h2>VLAN ตามอุปกรณ์{chosen ? ` · ${chosen}` : ""}</h2><p>Service ใช้ชื่อที่ตั้งใน VLAN Name · ข้อมูลจาก discovery ล่าสุด</p></div>
        {chosen && <button className="secondary" onClick={() => onChoose("")}>แสดงทุกอุปกรณ์</button>}
      </div>
      <div className="table-scroll vlan-table-scroll" tabIndex={0} role="region" aria-label="VLAN ?????????? ?????????????"><table>
        <thead><tr><th>Device</th><th>VLAN ID</th><th>VLAN Name / Service</th></tr></thead>
        <tbody>{assignments.map(({ vlan, device, name }) => <tr key={`${device}:${vlan.vlan_id}`}>
          <td><button className="text-link" onClick={() => onChoose(device)}>{device}</button></td>
          <td className="mono">{vlan.vlan_id}</td>
          <td>{name === undefined ? <>{vlan.vlan_name || "ไม่พบชื่อ VLAN"}<small className="subtle"> · ชื่อรวมจากข้อมูลเดิม ต้อง discovery ใหม่เพื่อยืนยันชื่อรายอุปกรณ์</small></> : name || "ไม่พบชื่อ VLAN"}</td>
        </tr>)}{!assignments.length && <tr><td colSpan={3}>ไม่พบข้อมูล VLAN ของอุปกรณ์ที่ตรงกับตัวกรอง</td></tr>}</tbody>
      </table></div>
    </section>
  </>;
}
