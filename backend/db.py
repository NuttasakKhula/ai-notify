import os
from pathlib import Path
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name('.env'))


@contextmanager
def database():
    url = os.getenv('DATABASE_URL')
    if not url:
        raise RuntimeError('Configure DATABASE_URL in backend/.env')
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        yield conn


def migrate():
    with database() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(812001)')
        conn.execute(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))


if __name__ == '__main__':
    migrate()
    print('Database migrations applied.')
