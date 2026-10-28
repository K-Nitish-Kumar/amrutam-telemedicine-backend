from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_backend: str = "redis"
    jwt_secret: str = ""
    data_encryption_keys: str = ""
    metrics_token: str = ""
    cors_origins: str = "http://localhost:3000"
    payments_mode: str = "disabled"
    log_level: str = "INFO"
    tracing_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318/v1/traces"
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    admin_email: str = ""
    admin_password: str = ""

    @field_validator("rate_limit_backend")
    @classmethod
    def check_limiter(cls, val: str) -> str:
        if val not in {"redis", "memory"}:
            raise ValueError("RATE_LIMIT_BACKEND must be redis or memory")
        return val

    @model_validator(mode="after")
    def verify_secrets(self):
        if not self.database_url:
            raise ValueError("DATABASE_URL is required")
        if len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        if not self.data_encryption_keys:
            raise ValueError("DATA_ENCRYPTION_KEYS is required")
        from cryptography.fernet import Fernet
        for key in self.data_encryption_keys.split(","):
            Fernet(key.strip().encode())
        if self.app_env == "production":
            if not self.database_url.startswith("postgresql+"):
                raise ValueError("Production requires PostgreSQL")
            if self.rate_limit_backend != "redis":
                raise ValueError("Production must use distributed Redis rate limiting")
            if self.payments_mode == "demo":
                raise ValueError("Demo payment settlement cannot run in production")
            if not self.metrics_token:
                raise ValueError("METRICS_TOKEN required in production")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
