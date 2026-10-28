# Architecture

The browser uses Next.js `/api/*`, forwarding to FastAPI through server-side `BACKEND_URL`. PostgreSQL stores organizations, users, sessions, topology, incidents, reports and queues. `db.py` applies the repeatable versioned SQL schema.

Employees access their organization; administrators manage organizations/accounts. Device credentials use Fernet encryption. Organization webhook keys authenticate incoming incidents.

The worker runs discovery and analysis separately. Advisory locks prevent duplicate processing. Interrupted jobs are marked failed after restart rather than blindly resending Teams notifications. Schedules require a running worker; missed periods do not create unlimited catch-up jobs.

Ai Notify starts disabled. Disabled analysis retains logs and suppresses processing; enabling does not replay suppressed incidents. This switch does not disable discovery. Start only web/API for a passive preview.

Tests mock SSH, Ollama and Teams. Passing tests do not prove live connectivity.
