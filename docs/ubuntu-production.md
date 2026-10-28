# Production deployment

Requires Docker Compose, DNS, TLS certificates and an existing ELK Docker network. This repository does not provision cloud infrastructure, ELK or Ollama.

Copy `deploy/production.env.example` to `backend/.env`. Generate secrets using Python with backend dependencies installed:

```sh
python -c "import secrets; print(secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use the hex password for both `POSTGRES_PASSWORD` and the password in `DATABASE_URL`. Use the Fernet key for `CREDENTIAL_ENCRYPTION_KEY`. Set `APP_ORIGIN` to your exact HTTPS origin and keep `COOKIE_SECURE=true`. Set `BIND_IP` to your interface or `0.0.0.0`. Set `ELK_NETWORK` to the existing ElastAlert network found by inspecting its container and `docker network ls`.

Place certificates at `deploy/tls/server.crt` and `deploy/tls/server.key`. Restrict secret-file access and allow HTTPS through the firewall. Configure Ollama/model and Teams webhook. Leave allowed CIDRs empty until device networks are authorized. Cloud-to-device routing must be provided separately.

```sh
docker compose --env-file backend/.env -f compose.production.yaml build
docker compose --env-file backend/.env -f compose.production.yaml up -d postgres
docker compose --env-file backend/.env -f compose.production.yaml --profile tools run --rm migrate
docker compose --env-file backend/.env -f compose.production.yaml --profile tools run --rm migrate python bootstrap.py
docker compose --env-file backend/.env -f compose.production.yaml up -d api web nginx
```

Bootstrap prompts for the first admin. Open your HTTPS origin. The API is reachable on the ELK network at `ai-notify-api:8000`, without a published host port.

Only when ready to process queued jobs:

```sh
docker compose --env-file backend/.env -f compose.production.yaml --profile processing up -d worker
```

Stop processing with the same Compose arguments followed by `stop worker`. Back up PostgreSQL and the encryption key together; losing the key prevents decrypting SSH credentials. Keep backups outside Git.
