"""Generate local-only configuration and optionally the first admin account.

Existing configuration is never overwritten. Run --admin after PostgreSQL starts.
"""
import argparse
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--admin', action='store_true')
    args = parser.parse_args()
    backend = Path(__file__).parent
    config = backend / '.env'
    if not config.exists():
        password = secrets.token_urlsafe(32)
        text = (backend / '.env.example').read_text(encoding='utf-8')
        text = text.replace('change-this-local-password', password)
        text = text.replace('generate-with-command-in-README', Fernet.generate_key().decode())
        # Do not shadow the existing Notify.env destination with an empty variable.
        text = text.replace('TEAMS_WEBHOOK_URL=\n', '# TEAMS_WEBHOOK_URL is loaded from Notify.env when present\n')
        config.write_text(text + '\nPOSTGRES_PASSWORD=' + password + '\n', encoding='utf-8')
        print('Generated backend/.env with unique local database password and encryption key.')
    frontend = backend.parent / '.env.local'
    if not frontend.exists():
        frontend.write_text('BACKEND_URL=http://127.0.0.1:8000\n', encoding='utf-8')
    if args.admin:
        from bootstrap import main as bootstrap_admin
        bootstrap_admin()


if __name__ == '__main__':
    main()
