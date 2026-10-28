"""Create the first administrator interactively, without default credentials."""
import getpass
import uuid

from db import database, migrate
from security import password_hash, cipher


def main():
    cipher()
    migrate()
    email = input('Admin email: ').strip().lower()
    name = input('Admin name: ').strip()
    password = getpass.getpass('Admin password (at least 12 characters): ')
    if '@' not in email or not name or len(password) < 12:
        raise SystemExit('Valid email, name and password of at least 12 characters required.')
    with database() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(812002)')
        if conn.execute("SELECT 1 FROM users WHERE role = 'Admin'").fetchone():
            raise SystemExit('An administrator already exists. Use the admin UI to create additional users.')
        conn.execute('INSERT INTO users(id,email,name,password_hash,role) VALUES(%s,%s,%s,%s,%s)',
                     (uuid.uuid4(), email, name, password_hash(password), 'Admin'))
    print('Administrator created. Sign in through the web app.')


if __name__ == '__main__':
    main()
