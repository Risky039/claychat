"""Password hashing (scrypt) and session token helpers using standard library primitives."""

import hashlib
import hmac
import secrets

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LEN = 32
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128


def valid_password(value):
    return isinstance(value, str) and MIN_PASSWORD_LEN <= len(value) <= MAX_PASSWORD_LEN


def hash_password(password):
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_LEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password, encoded):
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected = bytes.fromhex(parts[5])
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (ValueError, OverflowError):
        return False
    return hmac.compare_digest(actual, expected)


def new_session_token():
    """Return a URL-safe 256-bit random session token."""
    return secrets.token_urlsafe(32)


def hash_token(token):
    """Hash a session token with SHA-256 before storing or looking it up."""
    if not isinstance(token, str) or not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

