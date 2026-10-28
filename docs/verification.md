# Verification without live integrations

After installing dependencies:

```powershell
npm.cmd run lint
npm.cmd run build
backend/.venv/Scripts/python -m pytest backend/tests -q
```

Database tests skip without `TEST_DATABASE_URL`. Use a separate disposable database, never application data:

```powershell
docker run --detach --name ai-notify-test-postgres -e POSTGRES_PASSWORD=local-integration-test-only -e POSTGRES_DB=ai_notify_test -p 127.0.0.1:55432:5432 postgres:17
$env:TEST_DATABASE_URL='postgresql://postgres:local-integration-test-only@127.0.0.1:55432/ai_notify_test'
$env:PYTHONUTF8='1'
backend/.venv/Scripts/python -m pytest backend/tests -q
```

Tests isolate database schemas and mock SSH/Ollama/Teams. Do not start a production worker. Optional browser tests require Google Chrome and a production build: `backend/.venv/Scripts/python -m pytest backend/tests/browser_smoke.py -q`.

See `RELEASE-CHECKS.md` for checks performed on this package.
