import uuid

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings
from app.security import (
    check_password,
    create_token,
    decode_token,
    decrypt_json,
    encrypt_json,
    hash_password,
    new_totp_secret,
    totp_for_step,
    verify_totp_step,
)


def valid_settings(**overrides):
    values = {
        "database_url": "postgresql+psycopg://someuser:somepassword@localhost:5432/testdb",
        "jwt_secret": "this-is-an-example-secret-longer-than-32-chars",
        "data_encryption_keys": Fernet.generate_key().decode(),
        "metrics_token": "separate-metrics-token-value",
        "rate_limit_backend": "memory",
        "payments_mode": "demo",
        "app_env": "development",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_hash_and_verify_password():
    encoded = hash_password("example-strong-password")
    assert encoded != "example-strong-password"
    assert check_password("example-strong-password", encoded)
    assert not check_password("bad-password", encoded)


def test_password_hash_random_salt():
    assert hash_password("same-secret") != hash_password("same-secret")


def test_encrypt_and_decrypt_json():
    payload = {"medications": [{"name": "Sample"}]}
    encrypted = encrypt_json(payload)
    assert "Sample" not in encrypted
    assert decrypt_json(encrypted) == payload


def test_signed_token_type_is_enforced():
    actor = uuid.uuid4()
    assert decode_token(create_token(actor)) == actor
    with pytest.raises(Exception):
        decode_token(create_token(actor, kind="mfa_challenge"), kind="access")


def test_totp_code_validation():
    secret = new_totp_secret()
    assert len(secret) >= 16
    assert len(totp_for_step(secret, 123456)) == 6
    assert verify_totp_step(secret, "not-a-code") is None
    assert verify_totp_step(secret, "123") is None


def test_settings_reject_missing_database_url():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        valid_settings(database_url="")


def test_settings_reject_weak_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        valid_settings(jwt_secret="short")


def test_settings_reject_invalid_fernet_key():
    with pytest.raises(ValidationError, match="Fernet key"):
        valid_settings(data_encryption_keys="invalid-key")


def test_production_requires_redis():
    with pytest.raises(ValidationError, match="Redis"):
        valid_settings(app_env="production", rate_limit_backend="memory", payments_mode="disabled")


def test_production_rejects_demo_payments():
    with pytest.raises(ValidationError, match="Demo payment"):
        valid_settings(app_env="production", rate_limit_backend="redis", payments_mode="demo")
