"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type PointerEvent, type FormEvent, type ReactNode } from "react";
import { api, ApiError, date, useResource } from "./api";
import { Icon } from "./ui-icon";
import { VlanTables, type Vlan } from "./vlan-tables";

type User = {
  id: string;
  name: string;
  email: string;
  role: "Admin" | "Employee";
  client_id: string | null;
  client_name: string | null;
  organizations?: { id: string; name: string }[];
};
type Client = {
  id: string;
  name: string;
  employees: number;
  created_at: string;
};
type Report = {
  id: string;
  device: string;
  status: string;
  output: string | null;
  error?: string;
  notification_status: string;
  created_at: string;
  model?: string;
};
type Log = {
  id: string;
  original_id: string;
  device: string;
  message: string;
  severity: string;
  occurred_at: string;
};
type Discovery = {
  started_at: string | null;
  progress_updated_at: string | null;
  progress: { stage: string; ip?: string; depth?: number; devices?: number; failed?: number; pending?: number } | null;
  id: string;
  seed_ip: string | null;
  ssh_username: string | null;
  max_depth: number;
  status: string;
  error: string | null;
  created_at: string;
};
type Device = {
  hostname?: string;
  ip?: string;
  platform?: string;
  serial_number?: string;
  vendor?: string;
  reachable?: boolean;
  snmp_location?: string;
};
type Edge = {
  source_device: string;
  target_device: string;
  source_port: string;
  target_port: string;
  discovery_protocol?: string;
};
type Topology = {
  created_at: string;
  snapshot: {
    devices: Record<string, Device>;
    links: Edge[];
    failures?: { ip: string; error: string }[];
  };
  vlans: {
    vlans?: Vlan[];
  };
};
type DashboardData = {
  counts: Record<string, number>;
  trend: { day: string; total: number; analyzed: number }[];
  recent: Report[];
  topology_updated_at: string | null;
};
const pages = [
  ["dashboard", "Overview", "ภาพรวมเครือข่าย"],
  ["discovery", "Discovery", "ค้นหาอุปกรณ์ในเครือข่าย"],
  ["topology", "Topology", "แผนผังการเชื่อมต่อ"],
  ["logs", "Log history", "ประวัติเหตุการณ์"],
  ["reports", "Analysis reports", "รายงานการวิเคราะห์"],
  ["clients", "Clients & users", "องค์กรและผู้ใช้งาน"],
  ["settings", "Settings", "การตั้งค่าระบบ"],
];

function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name="topology" size={30} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function Badge({ value }: { value: string }) {
  return (
    <span className={`badge ${value}`}>
      <span />
      {value}
    </span>
  );
}
function ResourceError({ error }: { error?: string }) {
  return error ? (
    <div className="notice error" role="alert">
      {error}
    </div>
  ) : null;
}
function Loading() {
  return (
    <div className="loading" role="status">
      <span className="spinner" />
      กำลังโหลดข้อมูล…
    </div>
  );
}
function SectionTitle({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
      </div>
      {children}
    </div>
  );
}

export default function Workspace({ section }: { section: string }) {
  const router = useRouter();
  const [user, setUser] = useState<User>();
  const [authError, setAuthError] = useState("");
  const [clientId, setClientId] = useState("");
  const [revision, setRevision] = useState(0);
  const [menu, setMenu] = useState(false);
  const clients = useResource<Client[]>(user ? "clients" : null, revision);
  const settings = useResource<{ notify_enabled: boolean }>(
    user ? "settings" : null,
    revision,
  );
  useEffect(() => {
    let active = true;
    api<User>("auth/me")
      .then((result) => {
        if (active) {
          setUser(result);
          setClientId(
            new URLSearchParams(window.location.search).get("client_id") ||
              result.client_id ||
              "",
          );
        }
      })
      .catch((error: Error) => {
        if (active) {
          if (error instanceof ApiError && error.status === 401)
            router.replace("/login");
          else setAuthError(error.message);
        }
      });
    return () => {
      active = false;
    };
  }, [router]);
  const selected = user?.role === "Employee"
    ? (clients?.data?.some((client) => client.id === clientId) ? clientId : clients?.data?.[0]?.id || "")
    : (clients?.data?.some((client) => client.id === clientId) ? clientId : "");
  const activeClientName = clients?.data?.find((client) => client.id === selected)?.name || user?.client_name;
  const query = `client_id=${encodeURIComponent(selected)}`;
  const refresh = () => setRevision((r) => r + 1);
  async function logout() {
    try {
      await api("auth/logout", { method: "POST" });
      router.replace("/login");
    } catch (error) {
      setAuthError((error as Error).message);
    }
  }
  if (!user)
    return (
      <main className="auth-loading">
        {authError ? (
          <>
            <ResourceError error={authError} />
            <Link href="/login">กลับหน้าเข้าสู่ระบบ</Link>
          </>
        ) : (
          <Loading />
        )}
      </main>
    );
  const adminPage = section === "clients" || section === "settings";
  return (
    <div className="app-shell">
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <Link className="brand" href="/dashboard">
          <span className="brand-symbol">
            <Icon name="topology" size={23} />
          </span>
          Ai Notify<span className="brand-dot">.</span>
        </Link>
        <div className="workspace-label">
          <span className="workspace-avatar">
            {(activeClientName || "A").slice(0, 1)}
          </span>
          <div>
            <strong>{activeClientName || "Admin workspace"}</strong>
            <small>Network operations</small>
          </div>
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="เมนูหลัก">
          {pages
            .filter(
              ([id]) =>
                user.role === "Admin" || !["clients", "settings"].includes(id),
            )
            .map(([id, label]) => (
              <Link
                key={id}
                href={`/${id}${selected ? `?client_id=${selected}` : ""}`}
                className={`nav-link ${section === id ? "active" : ""}`}
                onClick={() => setMenu(false)}
                aria-current={section === id ? "page" : undefined}
              >
                <Icon name={id} />
                {label}
                {section === id && <span className="active-dot" />}
              </Link>
            ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="support-note">
            <Icon name="bell" />
            <strong>ทุกเหตุการณ์ มีบริบท</strong>
            <p>
              เชื่อมโยง log กับ topology
              <br />
              เพื่อเข้าใจเหตุการณ์ได้ชัดเจนขึ้น
            </p>
          </div>
          <div className="profile">
            <span className="avatar">{user.name.slice(0, 1)}</span>
            <div>
              <strong>{user.name}</strong>
              <small>{user.role}</small>
            </div>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="menu-toggle icon-button"
            aria-label="เปิดหรือปิดเมนู"
            onClick={() => setMenu(!menu)}
          >
            ☰
          </button>
          <div className="breadcrumb">
            Workspace <span>/</span>{" "}
            <strong>{pages.find((p) => p[0] === section)?.[1]}</strong>
          </div>
          <div className="topbar-right">
            {settings?.data && (
              <span
                className={`status-indicator ${settings.data.notify_enabled ? "enabled" : ""}`}
              >
                <i />
                {settings.data.notify_enabled
                  ? "Ai Notify enabled"
                  : "Ai Notify paused"}
              </span>
            )}
            <span className="avatar small">{user.name.slice(0, 1)}</span>
            <button className="logout-button" onClick={logout}>
              <Icon name="logout" size={18} />
              ออกจากระบบ
            </button>
          </div>
        </header>
        <main className="content">
          <ResourceError
            error={authError || clients?.error || settings?.error}
          />
          {!adminPage && (
            <div className="organization-picker">
              <label htmlFor="organization">องค์กรที่กำลังดู</label>
              <select
                id="organization"
                value={selected}
                onChange={(e) => {
                  setClientId(e.target.value);
                  router.replace(`/${section}?client_id=${encodeURIComponent(e.target.value)}`);
                }}
              >
                <option value="">เลือกองค์กร</option>
                {clients?.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {adminPage && user.role !== "Admin" ? (
            <Empty title="เฉพาะผู้ดูแลระบบ">คุณไม่มีสิทธิ์เข้าถึงหน้านี้</Empty>
          ) : section === "clients" ? (
            <Clients
              currentUserId={user.id}
              clients={clients?.data || []}
              revision={revision}
              refresh={refresh}
            />
          ) : section === "settings" ? (
            <Settings revision={revision} refresh={refresh} />
          ) : !selected ? (
            <Empty title="เลือกองค์กรเพื่อเริ่มต้น">
              เลือกองค์กรด้านบนเพื่อดูข้อมูล หรือ{" "}
              <Link href="/clients">เพิ่มองค์กรใหม่</Link>
            </Empty>
          ) : (
            <div key={selected}>
              {section === "dashboard" ? (
                <Dashboard query={query} />
              ) : section === "discovery" ? (
                <DiscoveryPage key={selected} clientId={selected} query={query} />
              ) : section === "topology" ? (
                <TopologyPage key={query} query={query} />
              ) : (
                <History
                  kind={section === "logs" ? "logs" : "reports"}
                  query={query}
                />
              )}
            </div>
          )}
          <footer className="page-footer">
            <span>Ai Notify · Network intelligence</span>
            <span>ข้อมูลแยกตามองค์กร · อัปเดตทุก 5 วินาที</span>
          </footer>
        </main>
      </div>
    </div>
  );
}

function Dashboard({ query }: { query: string }) {
  const resource = useResource<DashboardData>(`dashboard?${query}`);
  const data = resource?.data;
  return (
    <>
      <SectionTitle eyebrow="YOUR NETWORK AT A GLANCE" title="ภาพรวมเครือข่าย">
        <Link href={`/discovery?${query}`} className="primary">
          <Icon name="discovery" size={18} />
          Discover topology
        </Link>
      </SectionTitle>
      <p className="page-description">
        ติดตามเครือข่ายและผลวิเคราะห์เหตุการณ์ขององค์กรในพื้นที่เดียว
      </p>
      <ResourceError error={resource?.error} />
      {!resource ? (
        <Loading />
      ) : (
        data && (
          <>
            <div className="stats-grid">
              {[
                ["devices", "อุปกรณ์ที่ค้นพบ", "topology"],
                ["logs", "Log ทั้งหมด", "logs"],
                ["analyzed", "วิเคราะห์สำเร็จ", "reports"],
                ["sent", "ส่ง Teams สำเร็จ", "bell"],
              ].map(([key, label, icon]) => (
                <article className="stat-card" key={key}>
                  <div className="stat-top">
                    <span>{label}</span>
                    <span className="stat-icon">
                      <Icon name={icon} />
                    </span>
                  </div>
                  <strong>{data.counts[key].toLocaleString()}</strong>
                  <small>
                    {key === "devices"
                      ? `${data.counts.links} connections ใน snapshot ล่าสุด`
                      : key === "analyzed"
                        ? `${data.counts.pending} รอประมวลผล · ${data.counts.failed} ไม่สำเร็จ`
                        : key === "sent"
                          ? "จากรายงานที่วิเคราะห์แล้ว"
                          : "เหตุการณ์ที่รับเข้าและบันทึกแล้ว"}
                  </small>
                </article>
              ))}
            </div>
            <div className="dashboard-grid">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Analysis activity</h2>
                    <p>จำนวนรายงานใน 7 วันล่าสุด (UTC)</p>
                  </div>
                  <span className="period">Last 7 days</span>
                </div>
                <div className="chart-legend">
                  <i />
                  วิเคราะห์สำเร็จ <i className="light" />
                  รายงานทั้งหมด
                </div>
                <div
                  className="bar-chart"
                  role="img"
                  aria-label="กราฟจำนวนรายงาน 7 วันล่าสุด"
                >
                  {data.trend.map((day) => (
                    <div className="bar-column" key={day.day}>
                      <div className="bar-area">
                        <span
                          className="bar-total"
                          style={{
                            height: `${(day.total / Math.max(1, ...data.trend.map((d) => d.total))) * 100}%`,
                          }}
                          title={`${day.total} รายงาน`}
                        >
                          <span
                            className="bar-analyzed"
                            style={{
                              height: `${day.total ? (day.analyzed / day.total) * 100 : 0}%`,
                            }}
                          />
                        </span>
                        <span className="bar-value">{day.total}</span>
                      </div>
                      <small>
                        {new Date(day.day).toLocaleDateString("en-GB", {
                          day: "2-digit",
                          month: "short",
                        })}
                      </small>
                    </div>
                  ))}
                </div>
              </section>
              <section className="panel network-summary">
                <span className="eyebrow">CONNECTED PICTURE</span>
                <div className="summary-icon">
                  <Icon name="topology" size={48} />
                </div>
                <h2>รู้จักเครือข่ายของคุณ</h2>
                <p>
                  ดูเส้นทางเชื่อมต่อ อุปกรณ์ และพอร์ต
                  <br />
                  จากผล discovery ล่าสุด
                </p>
                <div className="summary-numbers">
                  <div>
                    <strong>{data.counts.devices}</strong>
                    <span>Devices</span>
                  </div>
                  <div>
                    <strong>{data.counts.links}</strong>
                    <span>Links</span>
                  </div>
                </div>
                <Link className="secondary full" href={`/topology?${query}`}>
                  เปิด Topology
                  <Icon name="arrow" size={17} />
                </Link>
                <small>อัปเดตล่าสุด {date(data.topology_updated_at)}</small>
              </section>
            </div>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>ผลวิเคราะห์ล่าสุด</h2>
                  <p>รายงาน RCA จาก Ollama และสถานะการแจ้งเตือน</p>
                </div>
                <Link className="text-link" href={`/reports?${query}`}>
                  ดูรายงานทั้งหมด ↗
                </Link>
              </div>
              {data.recent.length ? (
                <div className="report-feed">
                  {data.recent.map((report) => (
                    <article key={report.id}>
                      <span className="feed-icon">
                        <Icon name="reports" />
                      </span>
                      <div className="feed-body">
                        <div className="feed-title">
                          <strong>{report.device}</strong>
                          <Badge value={report.status} />
                        </div>
                        <p>
                          {report.output?.slice(0, 180) ||
                            "ยังไม่มีผลวิเคราะห์สำหรับเหตุการณ์นี้"}
                        </p>
                        <small>
                          {date(report.created_at)} · Teams:{" "}
                          {report.notification_status}
                        </small>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <Empty title="ยังไม่มีรายงาน">
                  เมื่อได้รับเหตุการณ์จาก ElastAlert2 ผลวิเคราะห์จะแสดงที่นี่
                </Empty>
              )}
            </section>
          </>
        )
      )}
    </>
  );
}

function DiscoveryProgress({ job }: { job: Discovery }) {
  const stages: Record<string, string> = {
    starting: "กำลังเตรียมการค้นหา",
    connecting: "กำลังเชื่อมต่อ SSH และตรวจชนิดอุปกรณ์",
    facts: "กำลังอ่านข้อมูลอุปกรณ์",
    neighbors: "กำลังค้นหาอุปกรณ์ข้างเคียงผ่าน CDP / LLDP",
    vlans: "กำลังอ่าน VLAN",
    unreachable: "เชื่อมต่ออุปกรณ์นี้ไม่ได้",
    device_done: "อ่านอุปกรณ์นี้เสร็จแล้ว",
    saving: "กำลังบันทึก Topology และ VLAN",
  };
  const p = job.progress;
  const terminal = ["completed", "failed", "cancelled"].includes(job.status);
  return <div className="discovery-progress" role="status">
    <strong>{job.status === "queued" ? "รอ worker รับงาน — ยังไม่ได้เริ่มค้นหา"
      : job.status === "completed" ? "ค้นหาและบันทึกผลเสร็จแล้ว"
      : job.status === "failed" ? "การค้นหาหยุดลง"
      : job.status === "cancelling" ? "กำลังหยุดการค้นหา…"
      : job.status === "cancelled" ? "หยุดการค้นหาแล้ว"
      : stages[p?.stage ?? ""] ?? "รับงานแล้ว — ยังไม่มีรายละเอียดขั้นตอน"}</strong>
    {p && <>
      {p.ip && <div>{terminal ? "อุปกรณ์ล่าสุด" : "อุปกรณ์"}: <span className="mono">{p.ip}</span> · Depth {p.depth}</div>}
      {p.devices !== undefined && <div>อ่านได้ {p.devices} อุปกรณ์{p.failed !== undefined && ` · ติดต่อไม่ได้ ${p.failed}`}{!terminal && p.pending !== undefined && ` · รอตรวจ ${p.pending}`}</div>}
    </>}
    {job.started_at && <div>เริ่มทำงาน: {date(job.started_at)}</div>}
    {job.progress_updated_at && <div className="subtle">อัปเดตขั้นตอนล่าสุด: {date(job.progress_updated_at)}</div>}
  </div>;
}

function DiscoveryPage({
  clientId,
  query,
}: {
  clientId: string;
  query: string;
}) {
  const [credentialRows, setCredentialRows] = useState([0]);
  const nextCredentialId = useRef(1);
  const [remember, setRemember] = useState(false);
  const [revision, setRevision] = useState(0);
  const resource = useResource<Discovery[]>(`discoveries?${query}`, revision);
  const schedule = useResource<{seed_ip: string; repeat_days: number; next_run_at: string} | null>(`discovery-schedule?${query}`, revision);
  async function forgetSchedule() {
    setBusy(true);
    setError("");
    try {
      await api(`discovery-schedule?${query}`, { method: "DELETE" });
      setRemember(false);
      setRevision((r) => r + 1);
      setSuccess("หยุดค้นหาอัตโนมัติและลบข้อมูลที่จำไว้แล้ว งานที่เริ่มแล้วจะดำเนินต่อจนจบ");
    } catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [success, setSuccess] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const values = Object.fromEntries(formData);
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await api("discoveries", {
        method: "POST",
        body: JSON.stringify({
          seed_ip: values.seed_ip,
          repeat_days: remember ? Number(values.repeat_days) : null,
          credentials: credentialRows.map((id) => ({
            username: formData.get(`ssh_username_${id}`),
            password: formData.get(`ssh_password_${id}`),
          })),
          client_id: clientId,
          max_depth: Number(values.max_depth),
        }),
      });
      form.reset();
      setCredentialRows([nextCredentialId.current++]);
      setSuccess("เพิ่มงาน discovery แล้ว ระบบจะอัปเดตสถานะด้านล่าง");
      setRevision((r) => r + 1);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const active = resource?.data?.some((d) =>
    ["queued", "running", "cancelling"].includes(d.status),
  );
  async function stopDiscovery(id: string) {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await api(`discoveries/${id}/cancel?${query}`, { method: "POST" });
      setRevision((r) => r + 1);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <SectionTitle eyebrow="DISCOVER YOUR NETWORK" title="ค้นหา Topology" />
      <p className="page-description">
        เริ่มจาก Seed IP แล้วค้นหาอุปกรณ์และการเชื่อมต่อผ่าน SSH, CDP และ LLDP
      </p>
      <div className="discovery-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>เริ่มการค้นหาใหม่</h2>
              <p>ใช้บัญชี SSH ที่มีสิทธิ์อ่านข้อมูลอุปกรณ์</p>
            </div>
            <span className="stat-icon">
              <Icon name="discovery" />
            </span>
          </div>
          <ResourceError error={schedule?.error} />
          {schedule?.data && <div className="notice" role="status">
            <p>จำข้อมูล Seed IP: {schedule.data.seed_ip} · ค้นหาอัตโนมัติทุก {schedule.data.repeat_days} วัน</p>
            <p>รอบถัดไป: {date(schedule.data.next_run_at)}</p>
            <button type="button" disabled={busy} onClick={forgetSchedule}>หยุดอัตโนมัติและไม่จำข้อมูล</button>
          </div>}
          <form onSubmit={submit} className="form-grid" autoComplete="off">
            <fieldset className="span-2" disabled={busy}>
              <legend>การจำข้อมูลและค้นหาอัตโนมัติ</legend>
              <button type="button" aria-pressed={!remember} className={!remember ? "primary" : "secondary"} onClick={() => setRemember(false)}>ไม่จำข้อมูล</button>{" "}
              <button type="button" aria-pressed={remember} className={remember ? "primary" : "secondary"} onClick={() => setRemember(true)}>จำข้อมูล</button>
              {remember ? <label>ค้นหาอุปกรณ์ใหม่ทุก ๆ
                <select name="repeat_days" defaultValue="1">
                  <option value="1">1 วัน</option>
                  <option value="7">1 อาทิตย์ (7 วัน)</option>
                  <option value="30">1 เดือน (30 วัน)</option>
                </select>
              </label> : <p className="subtle">ใช้ Seed IP และบัญชี SSH เฉพาะงานนี้ แล้วลบเมื่อจบงาน การเริ่มค้นหาจะยกเลิกตารางอัตโนมัติเดิมขององค์กร</p>}
              {remember && <p className="subtle">บันทึก Seed IP และเข้ารหัสบัญชี SSH สำหรับค้นหาซ้ำ แม้ปิดหน้าเว็บ โดยต้องเปิด worker ไว้</p>}
              <p className="subtle">ผล Topology ยังเก็บ IP ของอุปกรณ์ตามปกติ</p>
            </fieldset>
            <label className="span-2">
              Seed IP
              <input name="seed_ip" placeholder="192.0.2.10" required />
            </label>
            <div className="span-2">
              <p>เพิ่มบัญชี SSH ได้สูงสุด 10 ชุด ระบบจะลองบัญชีอื่นเมื่อยืนยันตัวตนไม่สำเร็จ</p>
              <p className="subtle">ใช้เฉพาะบัญชีที่เกี่ยวข้องกับเครือข่ายนี้ เพื่อลดการล็อกบัญชีจากการลองรหัสผิด</p>
            </div>
            {credentialRows.map((id, index) => (
              <fieldset key={id} className="span-2 form-grid" disabled={busy}>
                <legend>บัญชี SSH ชุดที่ {index + 1}</legend>
                <label>
                  SSH username
                  <input name={`ssh_username_${id}`} required autoComplete="off" maxLength={120} placeholder="network-user" />
                </label>
                <label>
                  SSH password
                  <input name={`ssh_password_${id}`} type="password" required autoComplete="new-password" maxLength={512} />
                </label>
                {credentialRows.length > 1 && (
                  <button type="button" onClick={() => setCredentialRows((rows) => rows.filter((row) => row !== id))}>
                    ลบบัญชีชุดที่ {index + 1}
                  </button>
                )}
              </fieldset>
            ))}
            <button type="button" className="span-2" disabled={busy || credentialRows.length >= 10}
              onClick={() => { const id = nextCredentialId.current++; setCredentialRows((rows) => [...rows, id]); }}>
              เพิ่มบัญชี SSH
            </button>
            <label className="span-2">
              ความลึกในการค้นหา (hops)
              <input
                name="max_depth"
                type="number"
                min={0}
                max={10}
                defaultValue={3}
                required
              />
            </label>
            <div className="span-2">
              <ResourceError error={error} />
              {success && (
                <p className="notice success" role="status">
                  {success}
                </p>
              )}
              <button className="primary" disabled={busy || active}>
                {busy
                  ? "กำลังส่ง…"
                  : active
                    ? resource?.data?.some((d) => d.status === "running") ? "กำลังค้นหาอุปกรณ์" : "มีงานรอคิว"
                    : "เริ่ม Discover Topology"}
                <Icon name="arrow" size={18} />
              </button>
            </div>
          </form>
        </section>
        <aside className="panel info-panel">
          <span className="eyebrow">HOW IT WORKS</span>
          <h2>
            จากหนึ่งอุปกรณ์
            <br />
            สู่ภาพรวมเครือข่าย
          </h2>
          <ol>
            <li>
              <strong>เชื่อมต่อ Seed IP</strong>
              <p>ระบบใช้ข้อมูล SSH ที่คุณระบุ</p>
            </li>
            <li>
              <strong>ค้นหาอุปกรณ์ข้างเคียง</strong>
              <p>อ่านพอร์ต การเชื่อมต่อ และ VLAN ตามระดับความลึก</p>
            </li>
            <li>
              <strong>สร้าง Topology</strong>
              <p>บันทึกผลและเปิดดูร่วมกันในองค์กร</p>
            </li>
          </ol>
          <p className="subtle">
            รหัสผ่าน SSH ถูกเข้ารหัสก่อนบันทึก และไม่แสดงกลับในหน้าเว็บ
          </p>
        </aside>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>ประวัติการค้นหา</h2>
          <span className="subtle">ล่าสุด 100 งาน</span>
        </div>
        <ResourceError error={resource?.error} />
        {!resource ? (
          <Loading />
        ) : !resource.data?.length ? (
          <Empty title="ยังไม่มีการค้นหา">
            กรอก Seed IP เพื่อเริ่มสร้างแผนผังแรก
          </Empty>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Seed IP</th>
                  <th>SSH user</th>
                  <th>Depth</th>
                  <th>สถานะ</th>
                  <th>เริ่มเมื่อ</th>
                </tr>
              </thead>
              <tbody>
                {resource.data.map((d) => (
                  <tr key={d.id}>
                    <td className="mono">{d.seed_ip || "—"}</td>
                    <td>{d.ssh_username ?? "ลบข้อมูลบัญชีแล้ว"}</td>
                    <td>{d.max_depth}</td>
                    <td>
                      <Badge value={d.status} />
                      <DiscoveryProgress job={d} />
                      {["queued", "running", "cancelling"].includes(d.status) && <button
                        className="secondary"
                        disabled={busy || d.status === "cancelling"}
                        onClick={() => stopDiscovery(d.id)}
                      >{d.status === "cancelling" ? "กำลังหยุด…" : "หยุดการค้นหา"}</button>}
                      {d.error && (
                        <small className="row-error">{d.error}</small>
                      )}
                    </td>
                    <td>{date(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

type SavedTopologyLayout = { positions: Record<string, { x: number; y: number }>; zoom: number };

function readTopologyLayout(key: string): SavedTopologyLayout {
  const fallback = { positions: {}, zoom: 1 };
  try {
    const saved = JSON.parse(localStorage.getItem(key) || "null");
    if (!saved || typeof saved.positions !== "object" || !saved.positions || Array.isArray(saved.positions)) return fallback;
    const positions: SavedTopologyLayout["positions"] = {};
    for (const [name, value] of Object.entries(saved.positions)) {
      const point = value as { x?: unknown; y?: unknown } | null;
      if (point && typeof point.x === "number" && typeof point.y === "number" && Number.isFinite(point.x) && Number.isFinite(point.y)) {
        positions[name] = { x: point.x, y: point.y };
      }
    }
    return { positions, zoom: typeof saved.zoom === "number" && saved.zoom >= 0.5 && saved.zoom <= 3 ? saved.zoom : 1 };
  } catch {
    return fallback;
  }
}

function TopologyPage({ query }: { query: string }) {
  const storageKey = `ai-notify:topology-layout:v1:${query}`;
  const [savedLayout] = useState(() => readTopologyLayout(storageKey));
  const [layoutError, setLayoutError] = useState("");
  function saveLayout(positions: SavedTopologyLayout["positions"], zoom: number) {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ positions, zoom }));
      setLayoutError("");
    } catch {
      setLayoutError("Unable to save device positions in this browser. Please enable site storage.");
    }
  }
  const [revision, setRevision] = useState(0);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState("");
  const resource = useResource<Topology | null>(`topology?${query}`, revision);
  async function resetTopology() {
    if (!window.confirm("ล้าง Topology และ VLAN ทั้งหมดขององค์กรที่เลือก? ประวัติการค้นหาและรายงานจะยังอยู่ และต้องค้นหาใหม่เพื่อสร้างแผนผังอีกครั้ง")) return;
    setResetting(true);
    setResetError("");
    try {
      await api(`topology?${query}`, { method: "DELETE" });
      setChosen("");
      setFilter("");
      setZoom(1);
      setLayout({ key: layoutKey, positions: {} });
      saveLayout({}, 1);
      setRevision((r) => r + 1);
    } catch (error) {
      setResetError((error as Error).message);
    } finally {
      setResetting(false);
    }
  }
  const [filter, setFilter] = useState(""),
    [chosen, setChosen] = useState(""),
    [zoom, setZoom] = useState(savedLayout.zoom);
  const data = resource?.data;
  const devices = Object.entries(data?.snapshot.devices || {});
  const edges = data?.snapshot.links || [];
  const names = [
    ...new Set([
      ...devices.map(([name]) => name),
      ...edges.flatMap((e) => [e.source_device, e.target_device]),
    ]),
  ];
  const layoutKey = query;
  const [layout, setLayout] = useState<{ key: string; positions: Record<string, { x: number; y: number }> }>({ key: layoutKey, positions: savedLayout.positions });
  const drag = useRef<{ name: string; pointerId: number; x: number; y: number; startX: number; startY: number; moved: boolean } | null>(null);
  function graphPoint(event: PointerEvent<SVGGElement>) {
    const matrix = event.currentTarget.ownerSVGElement?.getScreenCTM();
    return matrix ? new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse()) : null;
  }
  const positions = Object.fromEntries(
    names.map((name, i) => [
      name,
      (layout.key === layoutKey && layout.positions[name]) || {
        x: 480 + Math.cos((2 * Math.PI * i) / Math.max(1, names.length)) * 330,
        y: 280 + Math.sin((2 * Math.PI * i) / Math.max(1, names.length)) * 195,
      },
    ]),
  );
  function exportTopology() {
    if (!data) return;
    const exportedAt = new Date().toISOString();
    const payload = {
      schema_version: 1,
      exported_at: exportedAt,
      created_at: data.created_at,
      snapshot: data.snapshot,
      vlans: data.vlans,
      layout: { positions, zoom },
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `topology-${exportedAt.replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <>
      <SectionTitle eyebrow="MAP THE CONNECTIONS" title="Network Topology">
        <Link href={`/discovery?${query}`} className="secondary">
          <Icon name="discovery" size={18} />
          ค้นหาใหม่
        </Link>
      </SectionTitle>
      <p className="page-description">
        คลิกอุปกรณ์เพื่อเน้นการเชื่อมต่อ · ผล discovery ล่าสุด{" "}
        {date(data?.created_at)}
      </p>
      <ResourceError error={resource?.error} />
      {!resource ? (
        <Loading />
      ) : !data ? (
        <Empty title="ยังไม่มี Topology">
          เริ่ม discovery เพื่อสร้างแผนผังจากอุปกรณ์จริง
        </Empty>
      ) : (
        <>
          <ResourceError error={resetError} />
          <ResourceError error={layoutError} />
          <section className="panel topology-panel">
            <div className="panel-heading">
              <div>
                <h2>Physical connections</h2>
                <p>
                  {names.length} devices · {edges.length} links
                </p>
              </div>
              <div className="button-group">
                <button className="secondary" onClick={exportTopology}>Export JSON</button>
                <button className="secondary" disabled={resetting} onClick={resetTopology}>
                  {resetting ? "กำลังล้าง…" : "Reset Topology"}
                </button>
                <button
                  className="secondary"
                  aria-label="ซูมออก"
                  onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
                >
                  −
                </button>
                <button
                  className="secondary"
                  onClick={() => {
                    setZoom(1);
                    setChosen("");
                    setLayout({ key: layoutKey, positions: {} });
                    saveLayout({}, 1);
                  }}
                >
                  รีเซ็ตมุมมอง
                </button>
                <button
                  className="secondary"
                  aria-label="ซูมเข้า"
                  onClick={() => setZoom((z) => Math.min(3, z + 0.25))}
                >
                  +
                </button>
              </div>
            </div>
            <div className="graph-scroll">
              <svg
                viewBox={`0 0 ${960 / zoom} ${560 / zoom}`}
                className="topology-graph"
                role="img"
                aria-label="แผนผังการเชื่อมต่ออุปกรณ์"
              >
                {edges.map((e, i) => {
                  const source = positions[e.source_device];
                  const target = positions[e.target_device];
                  const dx = target.x - source.x;
                  const dy = target.y - source.y;
                  const distance = Math.hypot(dx, dy);
                  const ux = distance ? dx / distance : 1;
                  const uy = distance ? dy / distance : 0;
                  // Intersect the link with the 130 × 60 device card, then
                  // place each port just outside its own end of the link.
                  const boundary = Math.min(65 / Math.abs(ux), 30 / Math.abs(uy));
                  const offset = Math.min(boundary + 22, distance / 2);
                  const reversed = dx < 0;
                  const angle = Math.atan2(dy, dx) * 180 / Math.PI + (reversed ? 180 : 0);
                  const ports = [
                    { device: e.source_device, port: e.source_port, x: source.x + ux * offset, y: source.y + uy * offset, anchor: reversed ? "end" : "start" },
                    { device: e.target_device, port: e.target_port, x: target.x - ux * offset, y: target.y - uy * offset, anchor: reversed ? "start" : "end" },
                  ];
                  return (
                  <g
                    key={i}
                    opacity={
                      !chosen ||
                      [e.source_device, e.target_device].includes(chosen)
                        ? 1
                        : 0.15
                    }
                  >
                    <line
                      x1={positions[e.source_device].x}
                      y1={positions[e.source_device].y}
                      x2={positions[e.target_device].x}
                      y2={positions[e.target_device].y}
                      stroke="#9bbddc"
                      strokeWidth="2"
                    />
                    <title>{`${e.source_device} (${e.source_port}) ↔ ${e.target_device} (${e.target_port})`}</title>
                    {distance > 2 * boundary && ports.map((endpoint, side) => (
                      <text
                        key={side}
                        transform={`translate(${endpoint.x},${endpoint.y}) rotate(${angle})`}
                        y="-7"
                        textAnchor={endpoint.anchor as "start" | "end"}
                        fontSize="10"
                        fontWeight="600"
                        fill="#365777"
                        stroke="#f8fbff"
                        strokeWidth="4"
                        strokeLinejoin="round"
                        paintOrder="stroke"
                        className="graph-port-label"
                      >
                        <title>{`${endpoint.device}: ${endpoint.port || "Unknown port"}`}</title>
                        {(endpoint.port || "Unknown port")
                          .replace(/^TwentyFiveGigE/i, "Twe")
                          .replace(/^TenGigabitEthernet/i, "Te")
                          .replace(/^GigabitEthernet/i, "Gi")
                          .replace(/^FastEthernet/i, "Fa")
                          .replace(/^Ethernet/i, "Eth")}
                      </text>
                    ))}
                  </g>
                  );
                })}
                {names.map((name) => (
                  <g
                    key={name}
                    transform={`translate(${positions[name].x},${positions[name].y})`}
                    tabIndex={0}
                    role="button"
                    aria-label={`เลือกอุปกรณ์ ${name}`}
                    onPointerDown={(event) => {
                      if (event.button !== 0 || drag.current) return;
                      const point = graphPoint(event);
                      if (!point) return;
                      event.preventDefault();
                      event.currentTarget.focus();
                      event.currentTarget.setPointerCapture(event.pointerId);
                      drag.current = { name, pointerId: event.pointerId, x: point.x - positions[name].x, y: point.y - positions[name].y, startX: event.clientX, startY: event.clientY, moved: false };
                    }}
                    onPointerMove={(event) => {
                      const active = drag.current;
                      if (!active || active.pointerId !== event.pointerId || active.name !== name) return;
                      const point = graphPoint(event);
                      if (!point) return;
                      active.moved ||= Math.hypot(event.clientX - active.startX, event.clientY - active.startY) > 4;
                      if (!active.moved) return;
                      const bounds = event.currentTarget.ownerSVGElement!.viewBox.baseVal;
                      const position = { x: Math.max(65, Math.min(bounds.width - 65, point.x - active.x)), y: Math.max(30, Math.min(bounds.height - 30, point.y - active.y)) };
                      setLayout((previous) => ({ key: layoutKey, positions: { ...(previous.key === layoutKey ? previous.positions : {}), [name]: position } }));
                    }}
                    onPointerUp={(event) => {
                      const active = drag.current;
                      if (!active || active.pointerId !== event.pointerId) return;
                      drag.current = null;
                      event.currentTarget.releasePointerCapture(event.pointerId);
                      if (active.moved) saveLayout(positions, zoom);
                      else setChosen(chosen === name ? "" : name);
                    }}
                    onPointerCancel={() => { drag.current = null; }}
                    onLostPointerCapture={() => { drag.current = null; }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setChosen(chosen === name ? "" : name);
                      }
                    }}
                    className="graph-node"
                  >
                    <rect
                      x="-65"
                      y="-30"
                      width="130"
                      height="60"
                      rx="12"
                      fill={chosen === name ? "#e0eeff" : "white"}
                      stroke={chosen === name ? "#3975c6" : "#ccddeb"}
                      strokeWidth="2"
                    />
                    <circle
                      cx="0"
                      cy="-12"
                      r="4"
                      fill={
                        data.snapshot.devices[name]?.reachable
                          ? "#53ad98"
                          : "#94a3b8"
                      }
                    />
                    <text
                      y="8"
                      textAnchor="middle"
                      fontSize="11"
                      fill="#263e5a"
                    >
                      {name.length > 18 ? name.slice(0, 17) + "…" : name}
                    </text>
                    <text
                      y="23"
                      textAnchor="middle"
                      fontSize="9"
                      fill="#7a8ba0"
                    >
                      {data.snapshot.devices[name]?.ip || "Neighbor"}
                    </text>
                    <title>{name}</title>
                  </g>
                ))}
              </svg>
            </div>
            <div className="graph-caption">
              {chosen
                ? `กำลังเน้น: ${chosen}`
                : "ลากกล่องเพื่อจัดตำแหน่ง · คลิกเพื่อเน้นเส้นทาง"}
              <span>
                ● เข้าถึงได้　
                <span className="subtle">● อุปกรณ์ข้างเคียง / ไม่ทราบ</span>
              </span>
            </div>
          </section>
          <VlanTables vlans={data.vlans?.vlans || []} chosen={chosen} onChoose={setChosen} />
          <section className="panel">
            <div className="panel-heading">
              <h2>อุปกรณ์</h2>
              <input
                className="compact-input"
                aria-label="ค้นหาอุปกรณ์"
                placeholder="ค้นหาชื่อ, IP หรือ Serial Number…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Device</th>
                    <th>IP address</th>
                    <th>Platform</th>
                    <th>System Serial Number</th>
                    <th>Location</th>
                    <th>สถานะ</th>
                  </tr>
                </thead>
                <tbody>
                  {devices
                    .filter(([name, d]) =>
                      `${name} ${d.ip} ${d.serial_number || ""}`
                        .toLowerCase()
                        .includes(filter.toLowerCase()),
                    )
                    .map(([name, d]) => (
                      <tr key={name}>
                        <td>
                          <button
                            className="text-link"
                            onClick={() => setChosen(name)}
                          >
                            {name}
                          </button>
                        </td>
                        <td className="mono">{d.ip || "—"}</td>
                        <td>{d.platform || d.vendor || "—"}</td>
                        <td className="mono">{d.serial_number || "—"}</td>
                        <td>{d.snmp_location || "—"}</td>
                        <td>
                          <Badge
                            value={d.reachable ? "reachable" : "unknown"}
                          />
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <h2>Topology links {chosen && `· ${chosen}`}</h2>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Source device</th>
                    <th>Port</th>
                    <th>Target device</th>
                    <th>Port</th>
                    <th>Protocol</th>
                  </tr>
                </thead>
                <tbody>
                  {edges
                    .filter(
                      (e) =>
                        !chosen ||
                        [e.source_device, e.target_device].includes(chosen),
                    )
                    .map((e, i) => (
                      <tr key={i}>
                        <td>{e.source_device}</td>
                        <td className="mono">{e.source_port}</td>
                        <td>{e.target_device}</td>
                        <td className="mono">{e.target_port}</td>
                        <td>{e.discovery_protocol?.toUpperCase() || "—"}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            {!edges.length && (
              <Empty title="ไม่พบการเชื่อมต่อ">
                อุปกรณ์อาจไม่ได้เปิด CDP/LLDP หรือไม่มีเพื่อนบ้านที่ค้นพบ
              </Empty>
            )}
          </section>
          {!!data.snapshot.failures?.length && (
            <section className="panel">
              <div className="panel-heading">
                <h2>อุปกรณ์ที่ค้นหาไม่สำเร็จ</h2>
              </div>
              {data.snapshot.failures.map((f, i) => (
                <p key={i} className="notice">
                  {f.ip}: {f.error}
                </p>
              ))}
            </section>
          )}
        </>
      )}
    </>
  );
}

function History({ kind, query }: { kind: "logs" | "reports"; query: string }) {
  const [filters, setFilters] = useState(""),
    [page, setPage] = useState(1),
    [original, setOriginal] = useState<string | null>(null),
    [error, setError] = useState("");
  const resource = useResource<{ items: (Log & Report)[]; total: number }>(
    `${kind}?${query}&page=${page}${filters}`,
  );
  const isLog = kind === "logs";
  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const params = new URLSearchParams();
    for (const key of ["q", "device"])
      if (form.get(key)) params.set(key, String(form.get(key)));
    for (const key of ["start", "end"])
      if (form.get(key))
        params.set(
          key,
          new Date(
            `${form.get(key)}T${key === "end" ? "23:59:59.999" : "00:00:00"}`,
          ).toISOString(),
        );
    setFilters("&" + params.toString());
    setPage(1);
  }
  async function showOriginal(id: string) {
    try {
      setError("");
      setOriginal(JSON.stringify(await api(`logs/${id}/original`), null, 2));
    } catch (error) {
      setError((error as Error).message);
    }
  }
  return (
    <>
      <SectionTitle
        eyebrow={isLog ? "EVENT EXPLORER" : "INCIDENT INTELLIGENCE"}
        title={isLog ? "ประวัติ Log" : "รายงานการวิเคราะห์"}
      />
      <p className="page-description">
        {isLog
          ? "ค้นหาเหตุการณ์ตามข้อความ อุปกรณ์ และช่วงเวลา พร้อมตรวจสอบข้อมูลต้นฉบับ"
          : "อ่านผลวิเคราะห์ RCA จาก Ollama และส่งออกรายงานสำหรับทีม"}
      </p>
      <form className="filter-bar" onSubmit={search}>
        <label>
          ค้นหา
          <input
            name="q"
            placeholder={isLog ? "ค้นหาข้อความใน log…" : "ค้นหาเนื้อหารายงาน…"}
          />
        </label>
        <label>
          อุปกรณ์
          <input name="device" placeholder="ชื่ออุปกรณ์" />
        </label>
        <label>
          ตั้งแต่วันที่
          <input name="start" type="date" />
        </label>
        <label>
          ถึงวันที่
          <input name="end" type="date" />
        </label>
        <button className="primary">ค้นหา</button>
      </form>
      <ResourceError error={resource?.error || error} />
      {!resource ? (
        <Loading />
      ) : (
        resource.data && (
          <section className="panel">
            <div className="panel-heading">
              <h2>{isLog ? "Log entries" : "Analysis reports"}</h2>
              <span className="subtle">
                {resource.data.total.toLocaleString()} รายการ
              </span>
            </div>
            {!resource.data.items.length ? (
              <Empty title="ไม่พบข้อมูล">
                ลองเปลี่ยนตัวกรอง หรือรอเหตุการณ์ใหม่จาก ElastAlert2
              </Empty>
            ) : isLog ? (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>เวลา</th>
                      <th>Device</th>
                      <th>Severity</th>
                      <th>Message</th>
                      <th>Original</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resource.data.items.map((row) => (
                      <tr key={row.id}>
                        <td className="nowrap">{date(row.occurred_at)}</td>
                        <td>{row.device}</td>
                        <td>
                          <Badge value={row.severity} />
                        </td>
                        <td className="log-message mono">{row.message}</td>
                        <td>
                          <button
                            className="text-link"
                            onClick={() => showOriginal(row.original_id)}
                          >
                            ดู JSON
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="report-list">
                {resource.data.items.map((row) => (
                  <details className="report-detail" key={row.id}>
                    <summary>
                      <span className="feed-icon">
                        <Icon name="reports" />
                      </span>
                      <span className="report-heading">
                        <strong>{row.device}</strong>
                        <small>
                          {date(row.created_at)} ·{" "}
                          {row.model || "รอผลวิเคราะห์"}
                        </small>
                      </span>
                      <Badge value={row.status} />
                      <span className="expand-label">เปิดรายงาน ↓</span>
                    </summary>
                    <div className="report-content">
                      <p className="subtle">
                        Microsoft Teams:{" "}
                        <Badge value={row.notification_status} />
                      </p>
                      {row.error && (
                        <div className="notice error">{row.error}</div>
                      )}
                      {row.output ? (
                        <>
                          <div className="report-output">{row.output}</div>
                          <div className="export-row">
                            <strong>Export report</strong>
                            {["md", "json", "csv"].map((format) => (
                              <a
                                className="secondary"
                                key={format}
                                href={`/api/reports/${row.id}/export?format=${format}`}
                                download
                              >
                                {format.toUpperCase()} ↓
                              </a>
                            ))}
                            <button
                              className="secondary"
                              onClick={() => window.print()}
                            >
                              พิมพ์ / PDF
                            </button>
                          </div>
                        </>
                      ) : (
                        <p className="subtle">
                          {row.status === "suppressed"
                            ? "Ai Notify ปิดอยู่ หรือถูกปิดระหว่างประมวลผล จึงไม่มีการวิเคราะห์และส่งแจ้งเตือน"
                            : "ยังไม่มีผลวิเคราะห์"}
                        </p>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            )}
            <div className="pagination">
              <span>
                หน้า {page} / {Math.max(1, Math.ceil(resource.data.total / 50))}
              </span>
              <div className="button-group">
                <button
                  className="secondary"
                  disabled={page === 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  ก่อนหน้า
                </button>
                <button
                  className="secondary"
                  disabled={page * 50 >= resource.data.total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  ถัดไป
                </button>
              </div>
            </div>
          </section>
        )
      )}
      {original && (
        <div className="modal-backdrop" onClick={() => setOriginal(null)}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Original log JSON"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-heading">
              <h2>Original log</h2>
              <button
                className="secondary"
                autoFocus
                onClick={() => setOriginal(null)}
              >
                ปิด
              </button>
            </div>
            <pre>{original}</pre>
          </section>
        </div>
      )}
    </>
  );
}

function Clients({
  currentUserId,
  clients,
  revision,
  refresh,
}: {
  currentUserId: string;
  clients: Client[];
  revision: number;
  refresh: () => void;
}) {
  const users = useResource<User[]>("users", revision);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [webhook, setWebhook] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>, endpoint: string) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ webhook_key?: string }>(endpoint, {
        method: "POST",
        body: JSON.stringify({
          ...values,
          ...(endpoint === "users"
            ? { client_id: values.client_id || null }
            : {}),
        }),
      });
      if (result.webhook_key) setWebhook(result.webhook_key);
      setNotice(
        endpoint === "users" ? "สร้างบัญชีผู้ใช้แล้ว" : "เพิ่มองค์กรแล้ว",
      );
      form.reset();
      refresh();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function removeUser(user: User) {
    if (!window.confirm(`ลบผู้ใช้ ${user.name} (${user.email})? บัญชีนี้จะเข้าใช้งานไม่ได้ทันที ประวัติงานเดิมยังคงอยู่`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`users/${user.id}`, { method: "DELETE" });
      setNotice("ลบผู้ใช้แล้ว");
      refresh();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function removeClient(client: Client) {
    if (!window.confirm(`ลบองค์กร ${client.name} ถาวร? Topology, Discovery, Logs และ Reports ทั้งหมดขององค์กรจะถูกลบ ผู้ใช้ที่ไม่มีองค์กรอื่นจะถูกปิดบัญชี ส่วนผู้ใช้ที่มีองค์กรอื่นและ Admin จะยังอยู่ การลบนี้ย้อนกลับไม่ได้`)) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`clients/${client.id}`, { method: "DELETE" });
      setWebhook("");
      setNotice(`ลบองค์กร ${client.name} และข้อมูลขององค์กรแล้ว`);
      refresh();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function rotate(id: string) {
    if (
      !window.confirm(
        "สร้าง key ใหม่จะทำให้ key เดิมใช้งานไม่ได้ ต้องการดำเนินการหรือไม่?",
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ webhook_key: string }>(
        `clients/${id}/webhook-key`,
        { method: "POST" },
      );
      setWebhook(result.webhook_key);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <SectionTitle eyebrow="ADMINISTRATION" title="องค์กรและผู้ใช้งาน" />
      <p className="page-description">
        Employee ในองค์กรเดียวกันเข้าถึงข้อมูลร่วมกัน ผู้ดูแลระบบดูได้ทุกองค์กร
      </p>
      <ResourceError error={error || users?.error} />
      {notice && (
        <p className="notice success" role="status">
          {notice}
        </p>
      )}
      {webhook && (
        <div className="notice webhook-secret">
          <strong>Webhook key ใหม่ — แสดงครั้งเดียว</strong>
          <p>
            ตั้ง header <code>X-Webhook-Key</code> ใน ElastAlert2 แล้วเก็บ key
            ในที่ปลอดภัย
          </p>
          <code>{webhook}</code>
          <button className="secondary" onClick={() => setWebhook("")}>
            ซ่อน key
          </button>
        </div>
      )}
      <div className="admin-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>เพิ่มองค์กร</h2>
            <Icon name="clients" />
          </div>
          <form className="stack-form" onSubmit={(e) => submit(e, "clients")}>
            <label>
              ชื่อองค์กร
              <input
                name="name"
                required
                maxLength={120}
                placeholder="ชื่อบริษัท / องค์กร"
              />
            </label>
            <button className="primary" disabled={busy}>
              เพิ่มองค์กร +
            </button>
          </form>
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>สร้างบัญชีผู้ใช้งาน</h2>
          </div>
          <form className="form-grid" onSubmit={(e) => submit(e, "users")}>
            <label>
              ชื่อ
              <input name="name" required maxLength={120} />
            </label>
            <label>
              อีเมล
              <input name="email" type="email" required maxLength={254} />
            </label>
            <label>
              รหัสผ่าน
              <input
                name="password"
                type="password"
                minLength={12}
                maxLength={256}
                required
                autoComplete="new-password"
                placeholder="อย่างน้อย 12 ตัวอักษร"
              />
            </label>
            <label>
              สิทธิ์
              <select name="role">
                <option>Employee</option>
                <option>Admin</option>
              </select>
            </label>
            <label className="span-2">
              องค์กร (จำเป็นสำหรับ Employee)
              <select name="client_id" aria-label="Organization for new user">
                <option value="">เลือกองค์กร</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <button className="primary" disabled={busy}>
              สร้างบัญชี +
            </button>
          </form>
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>องค์กรทั้งหมด</h2>
          <span className="subtle">{clients.length} องค์กร</span>
        </div>
        {clients.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>องค์กร</th>
                  <th>ผู้ใช้ในองค์กร</th>
                  <th>สร้างเมื่อ</th>
                  <th>ElastAlert2</th>
                  <th>จัดการ</th>
                </tr>
              </thead>
              <tbody>
                {clients.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <strong>{c.name}</strong>
                    </td>
                    <td>{c.employees}</td>
                    <td>{date(c.created_at)}</td>
                    <td>
                      <button
                        className="text-link"
                        disabled={busy}
                        onClick={() => rotate(c.id)}
                      >
                        เปลี่ยน webhook key
                      </button>
                    </td>
                    <td><button className="secondary" disabled={busy} onClick={() => removeClient(c)} aria-label={`ลบองค์กร ${c.name}`}>ลบองค์กร</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="ยังไม่มีองค์กร">
            เพิ่มองค์กรแรก แล้วสร้างบัญชี Employee ให้ทีม
          </Empty>
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>ผู้ใช้งาน</h2>
        </div>
        {!users ? (
          <Loading />
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>ชื่อ</th>
                  <th>อีเมล</th>
                  <th>สิทธิ์</th>
                  <th>องค์กร</th>
                  <th>จัดการ</th>
                </tr>
              </thead>
              <tbody>
                {users.data?.map((u) => (
                  <tr key={u.id}>
                    <td>{u.name}</td>
                    <td>{u.email}</td>
                    <td>
                      <Badge value={u.role} />
                    </td>
                    <td>{u.role === "Admin" ? "ทุกองค์กร" : u.organizations?.map((organization) => organization.name).join(", ") || u.client_name || "—"}</td>
                    <td><button className="secondary" disabled={busy || u.id === currentUserId} onClick={() => removeUser(u)} aria-label={`ลบผู้ใช้ ${u.email}`}>{u.id === currentUserId ? "บัญชีของคุณ" : "ลบผู้ใช้"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <OrganizationMemberships users={users?.data || []} clients={clients} refresh={refresh} />
      <PasswordReset users={users?.data || []} />
    </>
  );
}

function OrganizationMemberships({ users, clients, refresh }: { users: User[]; clients: Client[]; refresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const employees = users.filter((user) => user.role === "Employee");
  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ added: boolean }>(`users/${values.get("user_id")}/organizations/${values.get("client_id")}`, { method: "PUT" });
      setNotice(result.added ? "เพิ่มผู้ใช้เข้าองค์กรแล้ว โดยยังอยู่ในองค์กรเดิม" : "ผู้ใช้นี้อยู่ในองค์กรที่เลือกแล้ว");
      refresh();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return <section className="panel">
    <div className="panel-heading"><div><h2>เพิ่มผู้ใช้เดิมเข้าองค์กร</h2><p>บัญชีเดียวอยู่ได้หลายองค์กร · Admin เข้าถึงทุกองค์กรอยู่แล้ว</p></div></div>
    <ResourceError error={error} />
    {notice && <p className="notice" role="status">{notice}</p>}
    <form className="form-grid" onSubmit={add}>
      <label>บัญชีผู้ใช้ที่มีอยู่<select aria-label="บัญชีผู้ใช้ที่มีอยู่" name="user_id" required defaultValue=""><option value="" disabled>เลือกผู้ใช้</option>{employees.map((user) => <option key={user.id} value={user.id}>{user.name} ({user.email})</option>)}</select></label>
      <label>องค์กรที่ต้องการเพิ่ม<select aria-label="องค์กรที่ต้องการเพิ่ม" name="client_id" required defaultValue=""><option value="" disabled>เลือกองค์กร</option>{clients.map((client) => <option key={client.id} value={client.id}>{client.name}</option>)}</select></label>
      <button className="primary" disabled={busy || !employees.length || !clients.length}>{busy ? "กำลังเพิ่ม…" : "เพิ่มเข้าองค์กร"}</button>
    </form>
  </section>;
}

function PasswordReset({ users }: { users: User[] }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`users/${values.get("user_id")}/password`, {
        method: "POST",
        body: JSON.stringify({ password: values.get("password") }),
      });
      form.reset();
      setNotice("เปลี่ยนรหัสผ่านแล้ว ผู้ใช้ต้องเข้าสู่ระบบใหม่");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>เปลี่ยนรหัสผ่านผู้ใช้</h2>
          <p>ยกเลิก session เดิมทั้งหมดของบัญชีที่เลือก รวมถึงบัญชีของคุณเอง</p>
        </div>
      </div>
      <form className="form-grid" onSubmit={submit}>
        <label>
          บัญชีที่ต้องการเปลี่ยน
          <select name="user_id" required aria-label="บัญชีที่ต้องการเปลี่ยน">
            <option value="">เลือกบัญชี</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name} · {u.email}
              </option>
            ))}
          </select>
        </label>
        <label>
          รหัสผ่านใหม่
          <input
            name="password"
            type="password"
            required
            minLength={12}
            maxLength={256}
            autoComplete="new-password"
          />
        </label>
        <div className="span-2">
          <ResourceError error={error} />
          {notice && <p className="notice success">{notice}</p>}
          <button className="secondary" disabled={busy}>
            บันทึกรหัสผ่านใหม่
          </button>
        </div>
      </form>
    </section>
  );
}

function Settings({
  revision,
  refresh,
}: {
  revision: number;
  refresh: () => void;
}) {
  const resource = useResource<{ notify_enabled: boolean; updated_at: string }>(
    "settings",
    revision,
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function toggle() {
    setBusy(true);
    setError("");
    try {
      await api("settings", {
        method: "PATCH",
        body: JSON.stringify({
          notify_enabled: !resource?.data?.notify_enabled,
        }),
      });
      refresh();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <SectionTitle eyebrow="SYSTEM CONTROLS" title="การตั้งค่าระบบ" />
      <p className="page-description">ควบคุมระบบ Ai Notify สำหรับทุกองค์กร</p>
      <ResourceError error={error || resource?.error} />
      {!resource ? (
        <Loading />
      ) : (
        resource.data && (
          <section className="panel settings-panel">
            <div className="settings-control">
              <span className="settings-icon">
                <Icon name="bell" size={30} />
              </span>
              <div>
                <h2>Ai Notify</h2>
                <p>
                  วิเคราะห์เหตุการณ์ด้วย Ollama และส่งรายงานเข้า Microsoft Teams
                </p>
              </div>
              <button
                className={`switch ${resource.data.notify_enabled ? "on" : ""}`}
                role="switch"
                aria-checked={resource.data.notify_enabled}
                aria-label="เปิดหรือปิด Ai Notify ทุกองค์กร"
                disabled={busy}
                onClick={toggle}
              >
                <span />
              </button>
            </div>
            <div className="settings-explanation">
              <Badge
                value={resource.data.notify_enabled ? "enabled" : "paused"}
              />
              <h3>
                {resource.data.notify_enabled
                  ? "ระบบกำลังรับงานวิเคราะห์ใหม่"
                  : "หยุดการวิเคราะห์และส่งแจ้งเตือน"}
              </h3>
              <p>
                เมื่อปิด ระบบยังบันทึก log ที่รับเข้ามา แต่ไม่เรียก Ollama
                และไม่ส่ง Teams งานวิเคราะห์ที่กำลังทำจะถูกยกเลิก
                และงานที่ข้ามไปจะไม่เริ่มใหม่อัตโนมัติเมื่อเปิดระบบ
              </p>
              <p>
                ข้อความที่ส่งออกไปแล้วเรียกคืนไม่ได้ หากกำลังส่ง Teams
                ระบบจะรอผลการส่งก่อนยืนยันว่าปิดแล้ว
              </p>
              <small>เปลี่ยนแปลงล่าสุด {date(resource.data.updated_at)}</small>
            </div>
          </section>
        )
      )}
    </>
  );
}
