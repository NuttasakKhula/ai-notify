"""Opt-in end-to-end smoke test against the production Next build and PostgreSQL.

Run after npm run build:
  python -m pytest backend/tests/browser_smoke.py -q
Requires playwright, installed Chrome, and TEST_DATABASE_URL.
External notifications and discovery workers are deliberately not started.
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
from playwright.sync_api import sync_playwright, expect
from psycopg.types.json import Jsonb
from db import database


def wait_for(url):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            if httpx.get(url).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.25)
    raise RuntimeError('Server did not start: ' + url)


def test_full_browser_workflow(db_env):
    root = Path(__file__).parents[2]
    artifacts = root / '.artifacts'
    artifacts.mkdir(exist_ok=True)
    env = {**os.environ, 'APP_ORIGIN':'http://localhost:3100', 'BACKEND_URL':'http://127.0.0.1:8100'}
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with (artifacts/'browser-backend.log').open('w') as backend_log, (artifacts/'browser-next.log').open('w') as next_log:
        backend = subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8100'], cwd=root/'backend',env=env,stdout=backend_log,stderr=backend_log,creationflags=flags)
        frontend = subprocess.Popen(['node',str(root/'node_modules/next/dist/bin/next'),'start','--port','3100'],cwd=root,env=env,stdout=next_log,stderr=next_log,creationflags=flags)
        try:
            wait_for('http://127.0.0.1:8100/health')
            wait_for('http://localhost:3100/login')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='chrome',headless=True)
                page = browser.new_page(viewport={'width':1440,'height':1050})
                page_errors=[]
                page.on('pageerror',lambda error:page_errors.append(str(error)))
                page.goto('http://localhost:3100/dashboard')
                expect(page).to_have_url('http://localhost:3100/login')
                page.screenshot(path=str(artifacts/'login-desktop.png'),full_page=True)
                page.get_by_label('ชื่อผู้ใช้หรืออีเมล',exact=True).fill('admin@example.test')
                page.get_by_label('รหัสผ่าน',exact=True).fill('test-password-123')
                page.get_by_role('button',name='เข้าสู่ระบบ',exact=True).click()
                expect(page.get_by_label('องค์กรที่กำลังดู')).to_be_visible()
                page.get_by_label('องค์กรที่กำลังดู').select_option(str(db_env['org_a']))
                expect(page.get_by_text('ยังไม่มีรายงาน',exact=True)).to_be_visible()
                page.screenshot(path=str(artifacts/'dashboard-desktop.png'),full_page=True)
                page.get_by_role('link',name='Discovery',exact=True).click()
                expect(page.get_by_label('Seed IP',exact=True)).to_be_visible()
                page.get_by_label('Seed IP',exact=True).fill('192.168.1.1')
                page.get_by_label('SSH username',exact=True).fill('netops')
                page.get_by_label('SSH password',exact=True).fill('test-only-ssh-password')
                page.get_by_role('button',name='เพิ่มบัญชี SSH',exact=True).click()
                page.get_by_label('SSH username',exact=True).nth(1).fill('access')
                page.get_by_label('SSH password',exact=True).nth(1).fill('access-secret')
                page.get_by_role('button',name='เพิ่มบัญชี SSH',exact=True).click()
                page.get_by_role('button',name='ลบบัญชีชุดที่ 3',exact=True).click()
                expect(page.get_by_label('SSH username',exact=True)).to_have_count(2)
                expect(page.get_by_role('button',name='ไม่จำข้อมูล',exact=True)).to_have_attribute('aria-pressed','true')
                page.get_by_role('button',name='จำข้อมูล',exact=True).click()
                page.get_by_label('ค้นหาอุปกรณ์ใหม่ทุก ๆ').select_option('7')
                page.screenshot(path=str(artifacts/'discovery-multiple-credentials.png'),full_page=True)
                page.get_by_role('button',name='เริ่ม Discover Topology').click()
                expect(page.get_by_text('queued',exact=True)).to_be_visible()
                expect(page.get_by_text('จำข้อมูล Seed IP: 192.168.1.1 · ค้นหาอัตโนมัติทุก 7 วัน',exact=True)).to_be_visible()
                page.get_by_role('button',name='หยุดอัตโนมัติและไม่จำข้อมูล',exact=True).click()
                expect(page.get_by_role('button',name='หยุดอัตโนมัติและไม่จำข้อมูล',exact=True)).to_have_count(0)
                with database() as conn:
                    assert conn.execute('SELECT * FROM discovery_schedules').fetchone() is None
                expect(page.get_by_text('รอ worker รับงาน — ยังไม่ได้เริ่มค้นหา',exact=True)).to_be_visible()
                from worker import claim
                from discovery_progress import save_progress
                job = claim('discoveries')
                import json
                from security import cipher
                credentials = json.loads(cipher().decrypt(job['ssh_credentials_encrypted'].encode()))
                assert credentials == [{'username':'netops','password':'test-only-ssh-password'}, {'username':'access','password':'access-secret'}]
                save_progress(job['id'], {'stage':'vlans','ip':'192.168.1.1','depth':0,'devices':1,'failed':0,'pending':2})
                expect(page.get_by_text('กำลังอ่าน VLAN',exact=True)).to_be_visible(timeout=10000)
                expect(page.get_by_text('อ่านได้ 1 อุปกรณ์ · ติดต่อไม่ได้ 0 · รอตรวจ 2',exact=True)).to_be_visible()
                page.screenshot(path=str(artifacts/'discovery-progress.png'),full_page=True)
                page.get_by_role('button',name='หยุดการค้นหา',exact=True).click()
                expect(page.get_by_text('กำลังหยุดการค้นหา…',exact=True)).to_be_visible()
                with database() as conn:
                    conn.execute("UPDATE discoveries SET status='cancelled',finished_at=now() WHERE id=%s", (job['id'],))
                expect(page.get_by_text('หยุดการค้นหาแล้ว',exact=True)).to_be_visible(timeout=10000)
                expect(page.get_by_label('SSH password',exact=True)).to_have_value('')
                expect(page.get_by_text('ลบข้อมูลบัญชีแล้ว',exact=True)).to_be_visible()
                page.get_by_role('link',name='Clients & users',exact=True).click()
                page.get_by_label('ชื่อองค์กร',exact=True).fill('Browser Organization')
                page.get_by_role('button',name='เพิ่มองค์กร +',exact=True).click()
                expect(page.get_by_text('เพิ่มองค์กรแล้ว',exact=True)).to_be_visible()
                page.get_by_role('button',name='ซ่อน key',exact=True).click()
                page.get_by_label('ชื่อ',exact=True).fill('Browser Employee')
                page.get_by_label('อีเมล',exact=True).fill('browser@example.test')
                page.get_by_label('รหัสผ่าน',exact=True).fill('browser-password-123')
                page.get_by_label('Organization for new user',exact=True).select_option(label='Browser Organization')
                page.get_by_role('button',name='สร้างบัญชี +',exact=True).click()
                expect(page.get_by_text('สร้างบัญชีผู้ใช้แล้ว',exact=True)).to_be_visible()
                page.get_by_role('link',name='Settings',exact=True).click()
                toggle=page.get_by_role('switch')
                expect(toggle).to_have_attribute('aria-checked','false')
                toggle.click()
                expect(toggle).to_have_attribute('aria-checked','true')
                toggle.click()
                expect(toggle).to_have_attribute('aria-checked','false')
                page.get_by_role('link',name='Log history',exact=True).click()
                expect(page.get_by_role('heading',name='ประวัติ Log',exact=True)).to_be_visible()
                page.get_by_label('ค้นหา',exact=True).fill('no results')
                page.get_by_role('button',name='ค้นหา',exact=True).click()
                expect(page.get_by_text('ไม่พบข้อมูล',exact=True)).to_be_visible()
                page.get_by_role('link',name='Topology',exact=True).click()
                expect(page.get_by_text('ยังไม่มี Topology',exact=True)).to_be_visible()
                # Test-only records in an isolated PostgreSQL schema; never seed the live app.
                with database() as conn:
                    discovery=conn.execute('SELECT id FROM discoveries WHERE client_id=%s',(db_env['org_a'],)).fetchone()
                    conn.execute("UPDATE discoveries SET status='completed',finished_at=now() WHERE id=%s",(discovery['id'],))
                    snapshot={'devices':{'SW-A':{'ip':'192.168.1.1','reachable':True},'SW-ACCESS':{'ip':'192.168.1.2','reachable':True}},
                              'links':[{'source_device':'SW-A','source_port':'Gi1/0/1','target_device':'SW-ACCESS','target_port':'Gi1/0/2','discovery_protocol':'cdp'}]}
                    conn.execute('INSERT INTO topologies(id,client_id,discovery_id,snapshot,vlans) VALUES(%s,%s,%s,%s,%s)',
                                 (uuid4(),db_env['org_a'],discovery['id'],Jsonb(snapshot),Jsonb({'vlans':[]})))
                page.reload()
                expect(page.get_by_text('Gi1/0/1',exact=True)).to_be_visible()
                page.get_by_role('button',name='เลือกอุปกรณ์ SW-A',exact=True).click()
                expect(page.get_by_role('heading',name='Topology links · SW-A',exact=True)).to_be_visible()
                page.screenshot(path=str(artifacts/'topology-desktop.png'),full_page=True)
                incoming=httpx.post('http://127.0.0.1:8100/webhook/incident',headers={'X-Webhook-Key':'key-a'},
                    json={'device_name':'SW-A','matches':[{'message':'Browser test link down','severity':'critical'}]})
                assert incoming.status_code==202
                output='รายงานทดสอบ: ตรวจสอบสายสัญญาณที่พอร์ต Gi1/0/1'
                with database() as conn:
                    conn.execute("UPDATE reports SET status='completed',output=%s,model='test-fixture',notification_status='sent',finished_at=now() WHERE id=%s",
                                 (output,incoming.json()['id']))
                page.get_by_role('link',name='Analysis reports',exact=True).click()
                expect(page.get_by_role('heading',name='รายงานการวิเคราะห์',exact=True)).to_be_visible()
                page.locator('summary').first.click()
                expect(page.get_by_text(output,exact=True)).to_be_visible()
                with page.expect_download() as download:
                    page.get_by_role('link',name='JSON ↓',exact=True).click()
                download.value.save_as(str(artifacts/'test-report.json'))
                assert output in (artifacts/'test-report.json').read_text(encoding='utf-8')
                page.get_by_role('link',name='Log history',exact=True).click()
                expect(page.get_by_text('Browser test link down',exact=True)).to_be_visible()
                page.get_by_role('button',name='ดู JSON',exact=True).click()
                expect(page.get_by_role('dialog',name='Original log JSON')).to_be_visible()
                page.get_by_role('button',name='ปิด',exact=True).click()
                page.get_by_role('link',name='Topology',exact=True).click()
                page.once('dialog',lambda dialog:dialog.dismiss())
                page.get_by_role('button',name='Reset Topology',exact=True).click()
                expect(page.get_by_role('img',name='แผนผังการเชื่อมต่ออุปกรณ์')).to_be_visible()
                page.once('dialog',lambda dialog:dialog.accept())
                page.get_by_role('button',name='Reset Topology',exact=True).click()
                expect(page.get_by_text('ยังไม่มี Topology',exact=True)).to_be_visible()
                page.get_by_role('button',name='ออกจากระบบ',exact=True).click()
                expect(page).to_have_url('http://localhost:3100/login')
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(artifacts/'login-mobile.png'),full_page=True)
                page.get_by_label('ชื่อผู้ใช้หรืออีเมล',exact=True).fill('browser@example.test')
                page.get_by_label('รหัสผ่าน',exact=True).fill('browser-password-123')
                page.get_by_role('button',name='เข้าสู่ระบบ',exact=True).click()
                expect(page.get_by_role('heading',name='ภาพรวมเครือข่าย',exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path=str(artifacts/'dashboard-mobile.png'),full_page=True)
                page.get_by_role('button',name='เปิดหรือปิดเมนู').click()
                expect(page.get_by_role('link',name='Clients & users',exact=True)).to_have_count(0)
                page.get_by_role('link',name='Discovery',exact=True).click()
                expect(page.get_by_label('Seed IP',exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.goto('http://localhost:3100/clients')
                expect(page.get_by_text('เฉพาะผู้ดูแลระบบ',exact=True)).to_be_visible()
                logout = page.get_by_role('button',name='ออกจากระบบ',exact=True)
                expect(logout).to_be_in_viewport()
                logout.click()
                expect(page).to_have_url('http://localhost:3100/login')
                page.goto('http://localhost:3100/dashboard')
                expect(page).to_have_url('http://localhost:3100/login')
                assert not page_errors, page_errors
                browser.close()
        finally:
            for process in (frontend, backend):
                process.terminate()
                process.wait(timeout=15)
