# Local setup (Windows PowerShell)

Use Node.js 24, Python 3.12+ and a running Docker engine. From the repository root:

```powershell
npm.cmd ci
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.lock.txt
backend/.venv/Scripts/python backend/setup_local.py
docker compose --env-file backend/.env up -d postgres
backend/.venv/Scripts/python backend/setup_local.py --admin
```

Admin creation prompts for email, name and a password of at least 12 characters. There is no default login. Protect the generated database password and encryption key.

Start API and web in separate terminals:

```powershell
backend/.venv/Scripts/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

```powershell
npm.cmd run dev
```

Open http://localhost:3000. This preview does not process queued jobs. Avoid `backend/run_local.py` for previews: it also starts the worker.

Create an organization and employees in Clients & users. Securely save the one-time organization webhook key. The Thai handbook is at `/handbook/index.html`.

For actual processing, configure `DISCOVERY_ALLOWED_CIDRS`, device access, `OLLAMA_URL`, `OLLAMA_MODEL` and `TEAMS_WEBHOOK_URL` in `backend/.env`. Provide network routing to device SSH addresses. Only when ready, run `backend/.venv/Scripts/python backend/worker.py`. Enable Ai Notify in Settings for analysis/delivery. Discovery runs independently of this switch.

Ctrl+C stops each terminal. Stop PostgreSQL with `docker compose --env-file backend/.env stop postgres`. Preserve its volume to retain data.
