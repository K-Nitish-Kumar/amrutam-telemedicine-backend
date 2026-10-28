import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from cryptography.fernet import Fernet, MultiFernet

from app.config import get_settings

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=2)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def check_password(password: str, encoded: str) -> bool:
    try:
        return _hasher.verify(encoded, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def create_token(user_id: uuid.UUID, *, kind: str = "access", ttl_minutes: int | None = None, mfa_verified: bool = False) -> str:
    settings = get_settings()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes or settings.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "kind": kind, "iat": datetime.now(timezone.utc),
                       "exp": expiry, "iss": "amrutam-api", "aud": "amrutam-client", "mfa_verified": mfa_verified, "jti": secrets.token_hex(12)},
                      settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, *, kind: str = "access") -> uuid.UUID:
    data = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"],
                      issuer="amrutam-api", audience="amrutam-client",
                      options={"require": ["sub", "exp", "iat", "iss", "aud", "kind"]})
    if data.get("kind") != kind:
        raise jwt.InvalidTokenError("Invalid token purpose")
    return uuid.UUID(data["sub"])


def _fernet() -> MultiFernet:
    return MultiFernet([Fernet(key.strip().encode()) for key in get_settings().data_encryption_keys.split(",")])


def encrypt_json(obj: dict) -> str:
    return _fernet().encrypt(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).decode()


def decrypt_json(value: str) -> dict:
    return json.loads(_fernet().decrypt(value.encode()))


def encrypt_string(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_string(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def totp_for_step(secret: str, step: int) -> str:
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def verify_totp_step(secret: str, code: str, last_used_step: int = -1) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdecimal():
        return None
    current = int(time.time()) // 30
    for step in (current - 1, current, current + 1):
        if step > last_used_step and hmac.compare_digest(totp_for_step(secret, step), code):
            return step
    return None


def totp_enrollment_uri(email: str, secret: str) -> str:
    return (f"otpauth://totp/Amrutam:{quote(email)}?secret={secret}"
            "&issuer=Amrutam&algorithm=SHA1&digits=6&period=30")
