"""Organization-scoped API for Ai Notify."""
import csv
import io
import ipaddress
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from typing import Literal

from fastapi import FastAPI, Depends, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from pydantic import BaseModel, Field, field_validator, model_validator
from psycopg import errors
from psycopg.types.json import Jsonb

from db import database
from security import cipher, digest, password_hash, verify_password

app = FastAPI(title='Ai Notify', version='1.0.0')


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path == '/api/discoveries':
        # Validation input can contain the entire credential list; never echo it.
        return JSONResponse(status_code=422, content={'detail': [
            {key: error[key] for key in ('loc', 'msg', 'type')}
            for error in exc.errors()]})
    return await request_validation_exception_handler(request, exc)
COOKIE = 'ai_notify_session'
DUMMY_HASH = password_hash(secrets.token_urlsafe(32))


@app.middleware('http')
async def protect_requests(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.url.path.startswith('/api/'):
        origin = request.headers.get('origin')
        if request.headers.get('x-requested-with') != 'ai-notify' or (origin and origin != os.getenv('APP_ORIGIN', 'http://localhost:3000')):
            return JSONResponse({'detail': 'Invalid request origin'}, status_code=403)
    if request.headers.get('content-length', '').isdigit() and int(request.headers['content-length']) > 2_000_000:
        return JSONResponse({'detail': 'Request too large'}, status_code=413)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.exception_handler(errors.UniqueViolation)
def unique_error(request, exc):
    return JSONResponse({'detail': 'Already exists, or a discovery is already active for this organization.'}, status_code=409)


@app.exception_handler(errors.ForeignKeyViolation)
def missing_reference_error(request, exc):
    return JSONResponse({'detail': 'ข้อมูลที่อ้างอิงถูกลบหรือไม่มีอยู่ กรุณาโหลดหน้าใหม่'}, status_code=409)


def current_user(request: Request):
    with database() as conn:
        row = conn.execute('''SELECT u.id,u.email,u.name,u.role,u.client_id,c.name AS client_name
            FROM sessions s JOIN users u ON u.id=s.user_id LEFT JOIN clients c ON c.id=u.client_id
            WHERE s.token_hash=%s AND s.expires_at > now() AND u.deleted_at IS NULL''', (digest(request.cookies.get(COOKIE, '')),)).fetchone()
    if not row:
        raise HTTPException(401, 'Please sign in')
    return row


def admin(user=Depends(current_user)):
    if user['role'] != 'Admin':
        raise HTTPException(403, 'Administrator access required')
    return user


def scope(user, requested: UUID | None):
    if user['role'] == 'Employee':
        requested = requested or user['client_id']
        with database() as conn:
            allowed = conn.execute('''SELECT 1 FROM users u WHERE u.id=%s AND u.deleted_at IS NULL
                AND (u.client_id=%s OR EXISTS (SELECT 1 FROM user_organizations m WHERE m.user_id=u.id AND m.client_id=%s))''',
                (user['id'], requested, requested)).fetchone()
        if not allowed:
            raise HTTPException(403, 'Organization access denied')
        return requested
    if not requested:
        raise HTTPException(400, 'Select an organization first')
    with database() as conn:
        if not conn.execute('SELECT 1 FROM clients WHERE id=%s', (requested,)).fetchone():
            raise HTTPException(404, 'Organization not found')
    return requested


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if '@' not in value:
            raise ValueError('Valid email required')
        return value


class LoginCredentials(Login):
    pass


@app.post('/api/auth/login')
def login(data: LoginCredentials, response: Response):
    with database() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (data.email,))
        conn.execute("DELETE FROM login_attempts WHERE created_at < now() - interval '1 day'")
        count = conn.execute("SELECT count(*) AS n FROM login_attempts WHERE email=%s AND created_at > now()-interval '15 minutes'", (data.email,)).fetchone()['n']
        if count >= 10:
            raise HTTPException(429, 'Too many attempts. Try again in 15 minutes.')
        conn.execute('INSERT INTO login_attempts(email) VALUES(%s)', (data.email,))
        user = conn.execute('SELECT * FROM users WHERE email=%s AND deleted_at IS NULL', (data.email,)).fetchone()
        valid = verify_password(data.password, user['password_hash'] if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, 'Email or password is incorrect')
    token = secrets.token_urlsafe(48)
    with database() as conn:
        conn.execute('DELETE FROM sessions WHERE expires_at < now()')
        conn.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(%s,%s,%s)',
                     (digest(token), user['id'], datetime.now(timezone.utc) + timedelta(hours=12)))
        conn.execute('DELETE FROM login_attempts WHERE email=%s', (data.email,))
    response.set_cookie(COOKIE, token, httponly=True, secure=os.getenv('COOKIE_SECURE', 'true').lower() == 'true', samesite='lax', max_age=43200, path='/')
    return {'ok': True}


@app.post('/api/auth/logout')
def logout(request: Request, response: Response):
    with database() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash=%s', (digest(request.cookies.get(COOKIE, '')),))
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return user


@app.get('/api/clients')
def clients(user=Depends(current_user)):
    with database() as conn:
        return conn.execute('''SELECT c.id,c.name,c.created_at,(SELECT count(*) FROM users u WHERE u.deleted_at IS NULL
            AND (u.client_id=c.id OR EXISTS (SELECT 1 FROM user_organizations m WHERE m.user_id=u.id AND m.client_id=c.id))) AS employees
          FROM clients c WHERE (%s OR c.id=%s OR EXISTS (SELECT 1 FROM user_organizations m WHERE m.user_id=%s AND m.client_id=c.id)) ORDER BY c.name''', (user['role'] == 'Admin', user['client_id'], user['id'])).fetchall()


class ClientInput(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r'.*\S.*')


@app.post('/api/clients', status_code=201)
def create_client(data: ClientInput, user=Depends(admin)):
    key, client_id = secrets.token_urlsafe(32), uuid4()
    with database() as conn:
        conn.execute('INSERT INTO clients(id,name,webhook_hash) VALUES(%s,%s,%s)', (client_id, data.name.strip(), digest(key)))
        conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)', (user['id'], 'client.created', Jsonb({'client_id': str(client_id)})))
    return {'id': client_id, 'name': data.name.strip(), 'webhook_key': key}


@app.post('/api/clients/{client_id}/webhook-key')
def rotate_webhook(client_id: UUID, user=Depends(admin)):
    scope(user, client_id)
    key = secrets.token_urlsafe(32)
    with database() as conn:
        conn.execute('UPDATE clients SET webhook_hash=%s WHERE id=%s', (digest(key), client_id))
        conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)', (user['id'], 'webhook.rotated', Jsonb({'client_id': str(client_id)})))
    return {'webhook_key': key}


@app.delete('/api/clients/{client_id}')
def delete_client(client_id: UUID, user=Depends(admin)):
    with database() as conn:
        # A short, atomic deletion freezes writers/queue claims while allowing reads.
        # This also prevents memberships or ingestion from racing the removal.
        conn.execute('''LOCK TABLE clients, users, user_organizations, sessions,
            discoveries, topologies, original_logs, log_history, reports, audit_events IN EXCLUSIVE MODE''')
        if not conn.execute('SELECT id FROM users WHERE id=%s AND deleted_at IS NULL', (user['id'],)).fetchone():
            raise HTTPException(401, 'Please sign in')
        organization = conn.execute('SELECT name FROM clients WHERE id=%s', (client_id,)).fetchone()
        if not organization:
            raise HTTPException(404, 'Organization not found')
        if conn.execute('''SELECT 1 FROM discoveries WHERE client_id=%s AND status IN ('running','cancelling')
            UNION ALL SELECT 1 FROM reports WHERE client_id=%s AND (status='running' OR notification_status='sending') LIMIT 1''',
            (client_id, client_id)).fetchone():
            raise HTTPException(409, 'องค์กรนี้มีงานกำลังทำงาน กรุณาหยุดหรือรอให้งานเสร็จก่อนลบองค์กร')
        affected = conn.execute('SELECT id,role FROM users WHERE client_id=%s', (client_id,)).fetchall()
        for account in affected:
            replacement = conn.execute('''SELECT client_id FROM user_organizations
                WHERE user_id=%s AND client_id<>%s ORDER BY created_at,client_id LIMIT 1''',
                (account['id'], client_id)).fetchone()
            remaining = replacement['client_id'] if replacement else None
            removed = account['role'] == 'Employee' and remaining is None
            conn.execute('''UPDATE users SET client_id=%s,
                deleted_at=CASE WHEN %s THEN coalesce(deleted_at,now()) ELSE deleted_at END WHERE id=%s''',
                (remaining, removed, account['id']))
            if removed:
                conn.execute('DELETE FROM sessions WHERE user_id=%s', (account['id'],))
        for table in ('user_organizations', 'topologies', 'discoveries', 'reports', 'log_history', 'original_logs'):
            conn.execute(f'DELETE FROM {table} WHERE client_id=%s', (client_id,))
        conn.execute('DELETE FROM clients WHERE id=%s', (client_id,))
        conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)',
            (user['id'], 'client.deleted', Jsonb({'client_id': str(client_id), 'name': organization['name']})))
    return {'ok': True}


class UserInput(Login):
    name: str = Field(min_length=1, max_length=120, pattern=r'.*\S.*')
    password: str = Field(min_length=12, max_length=256)
    client_id: UUID | None = None
    role: str = Field(default='Employee', pattern='^(Employee|Admin)$')


@app.get('/api/users')
def users(user=Depends(admin)):
    with database() as conn:
        return conn.execute('''SELECT u.id,u.name,u.email,u.role,u.client_id,c.name AS client_name,
            (SELECT coalesce(jsonb_agg(jsonb_build_object('id',o.id,'name',o.name) ORDER BY o.name),'[]'::jsonb)
             FROM clients o WHERE o.id=u.client_id OR EXISTS
             (SELECT 1 FROM user_organizations m WHERE m.user_id=u.id AND m.client_id=o.id)) AS organizations
            FROM users u LEFT JOIN clients c ON c.id=u.client_id WHERE u.deleted_at IS NULL ORDER BY u.created_at DESC''').fetchall()


@app.post('/api/users', status_code=201)
def create_user(data: UserInput, user=Depends(admin)):
    if data.role == 'Employee' and not data.client_id:
        raise HTTPException(422, 'Employee must belong to an organization')
    if data.client_id:
        scope(user, data.client_id)
    with database() as conn:
        row = conn.execute('INSERT INTO users(id,client_id,email,name,password_hash,role) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id,name,email,role,client_id',
                           (uuid4(), data.client_id, data.email, data.name.strip(), password_hash(data.password), data.role)).fetchone()
        conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)', (user['id'], 'user.created', Jsonb({'user_id': str(row['id'])})))
        return row


@app.put('/api/users/{user_id}/organizations/{client_id}')
def add_user_organization(user_id: UUID, client_id: UUID, user=Depends(admin)):
    with database() as conn:
        target = conn.execute('SELECT id,role,client_id FROM users WHERE id=%s AND deleted_at IS NULL FOR UPDATE', (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, 'User not found')
        if target['role'] != 'Employee':
            raise HTTPException(422, 'Administrators already have access to every organization')
        if not conn.execute('SELECT id FROM clients WHERE id=%s', (client_id,)).fetchone():
            raise HTTPException(404, 'Organization not found')
        added = None
        if target['client_id'] != client_id:
            added = conn.execute('INSERT INTO user_organizations(user_id,client_id) VALUES(%s,%s) ON CONFLICT DO NOTHING RETURNING user_id', (user_id, client_id)).fetchone()
        if added:
            conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)',
                         (user['id'], 'user.organization_added', Jsonb({'user_id':str(user_id),'client_id':str(client_id)})))
    return {'ok': True, 'added': bool(added)}


@app.delete('/api/users/{user_id}')
def delete_user(user_id: UUID, user=Depends(admin)):
    if user_id == user['id']:
        raise HTTPException(409, 'You cannot delete your own account')
    with database() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(812005)')
        actor = conn.execute('SELECT id FROM users WHERE id=%s AND deleted_at IS NULL', (user['id'],)).fetchone()
        if not actor:
            raise HTTPException(401, 'Please sign in')
        # Keep discovery and audit references while permanently revoking access.
        row = conn.execute('UPDATE users SET deleted_at=now() WHERE id=%s AND deleted_at IS NULL RETURNING id', (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'User not found')
        conn.execute('DELETE FROM sessions WHERE user_id=%s', (user_id,))
        conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)',
                     (user['id'], 'user.deleted', Jsonb({'user_id': str(user_id)})))
    return {'ok': True}


@app.get('/api/settings')
def settings(user=Depends(current_user)):
    with database() as conn:
        return conn.execute('SELECT notify_enabled,updated_at FROM settings WHERE id=1').fetchone()


class SettingsInput(BaseModel):
    notify_enabled: bool


class PasswordInput(BaseModel):
    password: str = Field(min_length=12, max_length=256)


@app.post('/api/users/{user_id}/password')
def reset_password(user_id: UUID, data: PasswordInput, user=Depends(admin)):
    with database() as conn:
        row = conn.execute('UPDATE users SET password_hash=%s WHERE id=%s AND deleted_at IS NULL RETURNING id', (password_hash(data.password), user_id)).fetchone()
        if not row:
            raise HTTPException(404, 'User not found')
        conn.execute('DELETE FROM sessions WHERE user_id=%s', (user_id,))
        conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)', (user['id'], 'password.reset', Jsonb({'user_id': str(user_id)})))
    return {'ok': True}


@app.patch('/api/settings')
def set_settings(data: SettingsInput, user=Depends(admin)):
    with database() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(812003)')
        row = conn.execute('UPDATE settings SET notify_enabled=%s,generation=generation+1,updated_at=now() WHERE id=1 RETURNING notify_enabled,updated_at', (data.notify_enabled,)).fetchone()
        conn.execute("UPDATE reports SET status='suppressed',notification_status='suppressed',finished_at=now() WHERE status IN ('queued','running')")
        conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)', (user['id'], 'notify.changed', Jsonb(data.model_dump())))
        return row


class SSHCredentialInput(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)


class DiscoveryInput(BaseModel):
    client_id: UUID | None = None
    seed_ip: str
    ssh_username: str | None = Field(default=None, min_length=1, max_length=120)
    ssh_password: str | None = Field(default=None, min_length=1, max_length=512)
    credentials: list[SSHCredentialInput] | None = Field(default=None, min_length=1, max_length=10)
    max_depth: int = Field(default=3, ge=0, le=10)
    repeat_days: Literal[1, 7, 30] | None = None

    @model_validator(mode='after')
    def validate_credentials(self):
        if self.credentials is not None:
            if self.ssh_username is not None or self.ssh_password is not None:
                raise HTTPException(422, 'Use credentials or the legacy SSH fields, not both')
        elif self.ssh_username is None or self.ssh_password is None:
            raise HTTPException(422, 'Provide at least one complete SSH credential set')
        return self

    @field_validator('seed_ip')
    @classmethod
    def validate_ip(cls, value):
        return str(ipaddress.ip_address(value.strip()))


@app.post('/api/discoveries', status_code=202)
def start_discovery(data: DiscoveryInput, user=Depends(current_user)):
    client_id = scope(user, data.client_id)
    from discovery_runner import allowed_ip
    if not allowed_ip(data.seed_ip):
        raise HTTPException(422, 'Seed IP is outside DISCOVERY_ALLOWED_CIDRS')
    credentials = [c.model_dump() for c in data.credentials] if data.credentials is not None else [
        {'username': data.ssh_username, 'password': data.ssh_password}]
    with database() as conn:
        conn.execute('SELECT id FROM clients WHERE id=%s FOR UPDATE', (client_id,))
        if data.repeat_days is None:
            conn.execute('DELETE FROM discovery_schedules WHERE client_id=%s', (client_id,))
        else:
            conn.execute('''INSERT INTO discovery_schedules(client_id,created_by,seed_ip,credentials_encrypted,max_depth,repeat_days,next_run_at)
              VALUES(%s,%s,%s,%s,%s,%s,now() + %s * interval '1 day')
              ON CONFLICT(client_id) DO UPDATE SET created_by=EXCLUDED.created_by,seed_ip=EXCLUDED.seed_ip,
              credentials_encrypted=EXCLUDED.credentials_encrypted,max_depth=EXCLUDED.max_depth,
              repeat_days=EXCLUDED.repeat_days,next_run_at=EXCLUDED.next_run_at''',
              (client_id, user['id'], data.seed_ip, cipher().encrypt(json.dumps(credentials).encode()).decode(),
               data.max_depth, data.repeat_days, data.repeat_days))
        return conn.execute('''INSERT INTO discoveries(id,client_id,created_by,seed_ip,ssh_username,ssh_password_encrypted,max_depth,ssh_credentials_encrypted)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id,status''',
          (uuid4(), client_id, user['id'], data.seed_ip, credentials[0]['username'],
           cipher().encrypt(credentials[0]['password'].encode()).decode(), data.max_depth,
           cipher().encrypt(json.dumps(credentials).encode()).decode())).fetchone()


@app.get('/api/discovery-schedule')
def discovery_schedule(client_id: UUID | None = None, user=Depends(current_user)):
    client_id = scope(user, client_id)
    with database() as conn:
        return conn.execute('SELECT host(seed_ip) AS seed_ip,repeat_days,next_run_at,max_depth FROM discovery_schedules WHERE client_id=%s', (client_id,)).fetchone()


@app.delete('/api/discovery-schedule')
def forget_discovery_schedule(client_id: UUID | None = None, user=Depends(current_user)):
    client_id = scope(user, client_id)
    with database() as conn:
        conn.execute('SELECT id FROM clients WHERE id=%s FOR UPDATE', (client_id,))
        conn.execute('DELETE FROM discovery_schedules WHERE client_id=%s', (client_id,))
    return {'remembered': False}


@app.get('/api/discoveries')
def discoveries(client_id: UUID | None = None, user=Depends(current_user)):
    client_id = scope(user, client_id)
    with database() as conn:
        return conn.execute('SELECT id,host(seed_ip) AS seed_ip,ssh_username,max_depth,status,error,created_at,started_at,finished_at,progress,progress_updated_at FROM discoveries WHERE client_id=%s ORDER BY created_at DESC LIMIT 100', (client_id,)).fetchall()


@app.get('/api/topology')
def topology(client_id: UUID | None = None, user=Depends(current_user)):
    client_id = scope(user, client_id)
    with database() as conn:
        return conn.execute('SELECT id,snapshot,vlans,created_at FROM topologies WHERE client_id=%s ORDER BY created_at DESC LIMIT 1', (client_id,)).fetchone()


@app.post('/api/discoveries/{job_id}/cancel')
def cancel_discovery(job_id: UUID, client_id: UUID | None = None, user=Depends(current_user)):
    client_id = scope(user, client_id)
    with database() as conn:
        job = conn.execute('SELECT status FROM discoveries WHERE id=%s AND client_id=%s FOR UPDATE', (job_id, client_id)).fetchone()
        if not job:
            raise HTTPException(404, 'Discovery not found')
        if job['status'] not in ('queued', 'running', 'cancelling'):
            return job
        status = 'cancelled' if job['status'] == 'queued' else 'cancelling'
        conn.execute("UPDATE discoveries SET status=%s,finished_at=CASE WHEN %s='cancelled' THEN now() ELSE NULL END WHERE id=%s", (status, status, job_id))
        return {'status': status}


@app.delete('/api/topology')
def reset_topology(client_id: UUID | None = None, user=Depends(current_user)):
    client_id = scope(user, client_id)
    with database() as conn:
        conn.execute('SELECT id FROM clients WHERE id=%s FOR UPDATE', (client_id,))
        if conn.execute("SELECT 1 FROM discoveries WHERE client_id=%s AND status IN ('queued','running','cancelling')", (client_id,)).fetchone():
            raise HTTPException(409, 'กรุณาหยุดการค้นหาและรอให้หยุดสำเร็จก่อนรีเซ็ต Topology')
        conn.execute('DELETE FROM topologies WHERE client_id=%s', (client_id,))
        conn.execute('INSERT INTO audit_events(actor_id,action,details) VALUES(%s,%s,%s)', (user['id'], 'topology.reset', Jsonb({'client_id':str(client_id)})))
    return {'reset': True}


def filter_clause(client_id, q, device, start, end, time_column, text_column):
    clauses, args = ['client_id=%s'], [client_id]
    start = start.replace(tzinfo=timezone.utc) if start and start.tzinfo is None else start
    end = end.replace(tzinfo=timezone.utc) if end and end.tzinfo is None else end
    if start and end and start > end:
        raise HTTPException(422, 'Start date must be before end date')
    for value, clause in [(q, f'{text_column} ILIKE %s'), (device, 'device ILIKE %s'), (start, f'{time_column} >= %s'), (end, f'{time_column} <= %s')]:
        if value is not None and value != '':
            clauses.append(clause)
            args.append(f'%{value}%' if clause.endswith('ILIKE %s') else value)
    return ' AND '.join(clauses), args


@app.get('/api/logs')
def logs(client_id: UUID | None = None, q: str = '', device: str = '', start: datetime | None = None, end: datetime | None = None,
         page: int = Query(1, ge=1), user=Depends(current_user)):
    where, args = filter_clause(scope(user, client_id), q, device, start, end, 'occurred_at', 'message')
    with database() as conn:
        total = conn.execute(f'SELECT count(*) AS n FROM log_history WHERE {where}', args).fetchone()['n']
        rows = conn.execute(f'SELECT * FROM log_history WHERE {where} ORDER BY occurred_at DESC,id LIMIT 50 OFFSET %s', [*args, (page-1)*50]).fetchall()
    return {'items': rows, 'total': total, 'page': page}


@app.get('/api/logs/{original_id}/original')
def original_log(original_id: UUID, user=Depends(current_user)):
    with database() as conn:
        row = conn.execute('SELECT * FROM original_logs WHERE id=%s', (original_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Log not found')
    scope(user, row['client_id'])
    return row


@app.get('/api/reports')
def reports(client_id: UUID | None = None, q: str = '', device: str = '', start: datetime | None = None, end: datetime | None = None,
            page: int = Query(1, ge=1), user=Depends(current_user)):
    where, args = filter_clause(scope(user, client_id), q, device, start, end, 'created_at', "coalesce(output,'')")
    with database() as conn:
        total = conn.execute(f'SELECT count(*) AS n FROM reports WHERE {where}', args).fetchone()['n']
        rows = conn.execute(f'SELECT * FROM reports WHERE {where} ORDER BY created_at DESC,id LIMIT 50 OFFSET %s', [*args, (page-1)*50]).fetchall()
    return {'items': rows, 'total': total, 'page': page}


@app.get('/api/reports/{report_id}/export')
def export_report(report_id: UUID, format: str = Query('md', pattern='^(md|json|csv)$'), user=Depends(current_user)):
    with database() as conn:
        row = conn.execute('SELECT * FROM reports WHERE id=%s', (report_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Report not found')
    scope(user, row['client_id'])
    if not row['output']:
        raise HTTPException(409, 'Report has no analysis output yet')
    if format == 'json':
        content, media = json.dumps(row, default=str, ensure_ascii=False, indent=2), 'application/json'
    elif format == 'csv':
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['Device', 'Created at', 'Model', 'Analysis'])
        values = [row['device'], str(row['created_at']), row['model'] or '', row['output']]
        writer.writerow(["'" + v if v.lstrip().startswith(('=', '+', '-', '@')) else v for v in values])
        content, media = '\ufeff' + stream.getvalue(), 'text/csv'
    else:
        content, media = row['output'], 'text/markdown'
    return Response(content, media_type=media, headers={'Content-Disposition': f'attachment; filename="ai-notify-{report_id}.{format}"'})


@app.get('/api/dashboard')
def dashboard(client_id: UUID | None = None, user=Depends(current_user)):
    client_id = scope(user, client_id)
    with database() as conn:
        counts = conn.execute('''SELECT count(*) AS reports, count(*) FILTER(WHERE status='completed') AS analyzed,
          count(*) FILTER(WHERE status='failed') AS failed, count(*) FILTER(WHERE status IN ('queued','running')) AS pending,
          count(*) FILTER(WHERE notification_status='sent') AS sent FROM reports WHERE client_id=%s''', (client_id,)).fetchone()
        counts['logs'] = conn.execute('SELECT count(*) AS n FROM log_history WHERE client_id=%s', (client_id,)).fetchone()['n']
        top = conn.execute('SELECT snapshot,created_at FROM topologies WHERE client_id=%s ORDER BY created_at DESC LIMIT 1', (client_id,)).fetchone()
        counts['devices'] = len(top['snapshot'].get('devices', {})) if top else 0
        counts['links'] = len(top['snapshot'].get('links', [])) if top else 0
        trend = conn.execute('''SELECT days.day::date AS day,count(r.id) AS total,count(r.id) FILTER(WHERE r.status='completed') AS analyzed
          FROM generate_series(current_date-6,current_date,interval '1 day') AS days(day)
          LEFT JOIN reports r ON r.client_id=%s AND r.created_at>=days.day AND r.created_at<days.day+interval '1 day'
          GROUP BY days.day ORDER BY days.day''', (client_id,)).fetchall()
        recent = conn.execute('SELECT id,device,status,output,notification_status,created_at FROM reports WHERE client_id=%s ORDER BY created_at DESC LIMIT 5', (client_id,)).fetchall()
    return {'counts': counts, 'trend': trend, 'recent': recent, 'topology_updated_at': top['created_at'] if top else None}


class Incident(BaseModel):
    device_name: str | None = Field(default=None, max_length=255)
    aggregation_key: str | None = Field(default=None, max_length=255)
    matches: list[dict] = Field(min_length=1, max_length=1000)


@app.post('/webhook/incident', status_code=202)
async def incident(request: Request):
    with database() as conn:
        client = conn.execute('SELECT id FROM clients WHERE webhook_hash=%s', (digest(request.headers.get('x-webhook-key', '')),)).fetchone()
    if not client:
        raise HTTPException(401, 'Invalid organization webhook key')
    raw = await request.body()
    if len(raw) > 2_000_000:
        raise HTTPException(413, 'Payload too large')
    try:
        payload = json.loads(raw)
        data = Incident.model_validate(payload)
    except ValueError:
        raise HTTPException(422, 'Expected an incident object with a non-empty matches array')
    event_key = request.headers.get('idempotency-key')
    if event_key and len(event_key) > 200:
        raise HTTPException(422, 'Idempotency key too long')
    host = payload.get('host') if isinstance(payload.get('host'), dict) else {}
    agent = payload.get('agent') if isinstance(payload.get('agent'), dict) else {}
    device = str(data.device_name or data.aggregation_key or host.get('name') or agent.get('hostname') or 'UNKNOWN_DEVICE')[:255]
    original_id, report_id = uuid4(), uuid4()
    with database() as conn:
        setting = conn.execute('SELECT * FROM settings WHERE id=1 FOR SHARE').fetchone()
        inserted = conn.execute('INSERT INTO original_logs(id,client_id,payload,event_key) VALUES(%s,%s,%s,%s) ON CONFLICT(client_id,event_key) DO NOTHING RETURNING id', (original_id, client['id'], Jsonb(payload), event_key)).fetchone()
        if not inserted:
            return conn.execute('SELECT r.id,r.status FROM reports r JOIN original_logs o ON o.id=r.original_id WHERE o.client_id=%s AND o.event_key=%s', (client['id'], event_key)).fetchone()
        now = datetime.now(timezone.utc)
        for match in data.matches:
            message = str(match.get('message') or match.get('log_message') or '')
            timestamp = match.get('@timestamp') or match.get('timestamp')
            try:
                occurred = datetime.fromisoformat(str(timestamp).replace('Z', '+00:00')) if timestamp else now
                if occurred.tzinfo is None:
                    occurred = occurred.replace(tzinfo=timezone.utc)
            except ValueError:
                occurred = now
            conn.execute('INSERT INTO log_history(id,client_id,original_id,device,message,severity,occurred_at) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                         (uuid4(), client['id'], original_id, device, message, str(match.get('severity', 'unknown'))[:80], occurred))
        status = 'queued' if setting['notify_enabled'] else 'suppressed'
        conn.execute('INSERT INTO reports(id,client_id,original_id,device,status,generation,notification_status) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                     (report_id, client['id'], original_id, device, status, setting['generation'], 'pending' if status == 'queued' else 'suppressed'))
    return {'id': report_id, 'status': status}


@app.get('/health')
def health():
    with database() as conn:
        conn.execute('SELECT 1')
    return {'status': 'ok'}
