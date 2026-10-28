"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "../components/api";
import { Icon } from "../components/ui-icon";

export default function Login() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api("auth/login", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(form)),
      });
      router.replace("/dashboard");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <section className="login-story">
        <Link className="brand" href="/login">
          <span className="brand-symbol">
            <Icon name="topology" size={25} />
          </span>
          Ai Notify<span className="brand-dot">.</span>
        </Link>
        <div className="login-intro">
          <span className="eyebrow">NETWORK INTELLIGENCE, SIMPLIFIED</span>
          <h1>
            เข้าใจเครือข่าย
            <br />
            เห็นภาพเดียวกัน
          </h1>
          <p>
            ค้นหาอุปกรณ์ ติดตามเหตุการณ์ และอ่านผลวิเคราะห์
            <br />
            ในพื้นที่ทำงานเดียวสำหรับทีมของคุณ
          </p>
          <div className="network-art" aria-hidden="true">
            <span className="art-node core">
              <Icon name="topology" size={32} />
            </span>
            <span className="art-node n1">
              <Icon name="logs" />
            </span>
            <span className="art-node n2">
              <Icon name="bell" />
            </span>
            <span className="art-node n3">
              <Icon name="reports" />
            </span>
            <div className="art-orbit" />
          </div>
        </div>
        <p className="subtle">Discover. Understand. Stay notified.</p>
      </section>
      <section className="login-form-side">
        <form className="login-form" onSubmit={submit}>
          <span className="eyebrow">WELCOME BACK</span>
          <h2>เข้าสู่ระบบ</h2>
          <p className="subtle">เข้าสู่พื้นที่ทำงาน Ai Notify ขององค์กร</p>
          <label>
            ชื่อผู้ใช้หรืออีเมล
            <input
              name="email"
              type="text"
              autoComplete="username"
              placeholder="Admin หรือ you@company.com"
              required
              maxLength={254}
            />
          </label>
          <label>
            รหัสผ่าน
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              placeholder="กรอกรหัสผ่านของคุณ"
              required
              maxLength={256}
            />
          </label>
          {error && (
            <div className="notice error" role="alert">
              {error}
            </div>
          )}
          <button className="primary full" disabled={busy}>
            {busy ? "กำลังเข้าสู่ระบบ…" : "เข้าสู่ระบบ"}
            <Icon name="arrow" />
          </button>
          <p className="login-help">
            ยังไม่มีบัญชี หรือต้องการเปลี่ยนรหัสผ่าน?
            <br />
            ติดต่อผู้ดูแลระบบของคุณ
          </p>
        </form>
      </section>
    </main>
  );
}
