import hashlib
import hmac
import os
import secrets

from cryptography.fernet import Fernet


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return salt + ':' + key.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split(':')
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def cipher() -> Fernet:
    key = os.getenv('CREDENTIAL_ENCRYPTION_KEY')
    if not key:
        raise RuntimeError('CREDENTIAL_ENCRYPTION_KEY is required')
    return Fernet(key.encode())
