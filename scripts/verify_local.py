#!/usr/bin/env python3
"""Read-only environment/DB readiness verification for native installation."""
import sys
from pathlib import Path

def main() -> int:
    # Validate local configuration before importing application/database settings.
    root = Path(__file__).resolve().parents[1]
    if not (root / ".env").exists():
        print("MISSING .env: copy .env.example to .env and configure it first.", file=sys.stderr)
        return 1

    from sqlalchemy import text
    from app.config import get_settings
    from app.db import make_engine

    settings = get_settings()
    if not settings.database_url.startswith("postgresql+psycopg://"):
        print("ERROR: Native installation must use a PostgreSQL psycopg connection URL.", file=sys.stderr)
        return 1
    if settings.rate_limit_backend != "memory":
        print("NOTE: RATE_LIMIT_BACKEND is not memory; Redis may be required.")
    engine = make_engine()
    try:
        with engine.connect() as connection:
            user = connection.execute(text("SELECT current_user")).scalar_one()
            name = connection.execute(text("SELECT current_database()")).scalar_one()
            migrated = connection.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
            version = (connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                       if migrated else None)
        print(f"PostgreSQL connected: {name} (role: {user})")
        if not version:
            print("Database is not migrated. Run: python -m alembic upgrade head")
            return 2
        print(f"Alembic migration: {version}")
        print("Rate limiting:", settings.rate_limit_backend)
        print("Ready to run API: http://127.0.0.1:8000/docs")
        return 0
    except Exception as exc:
        print(f"PostgreSQL check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

if __name__ == "__main__":
    raise SystemExit(main())