# Ai Notify

Network operations application: Next.js web UI, FastAPI API, PostgreSQL data and queues, SSH topology/VLAN discovery, Ollama analysis and Teams delivery.

## Structure

- `app/`: web UI and same-origin API proxy.
- `backend/`: API, users/organizations, SQL migrations, worker and discovery drivers.
- `backend/tests/`: tests with mocked external services.
- `deploy/`: Dockerfiles, HTTPS proxy and ElastAlert adapter.
- `public/handbook/`: Thai user handbook.

## Setup

- [Local setup](docs/run-web-windows-th.md)
- [Production deployment](docs/ubuntu-production.md)
- [ElastAlert integration](docs/elastalert-integration.md)
- [Architecture](docs/implementation.md)
- [Verification](docs/verification.md)
- [GitHub upload](docs/github-upload.md)

This is source code, not an offline distribution. Dependency installation needs package-registry access. Compose provides PostgreSQL. Supply ELK/ElastAlert, Ollama/models, Teams configuration, TLS certificates and routing to devices separately.

Never commit live environment files, credentials, webhook keys, database exports or discovery results. Example files contain placeholders.

No project-wide open-source license is granted by this package. The owner can add a license when ready to grant reuse rights. Third-party assets retain their own terms: see `public/handbook/README.txt` and `public/handbook/assets/OFL.txt`.
