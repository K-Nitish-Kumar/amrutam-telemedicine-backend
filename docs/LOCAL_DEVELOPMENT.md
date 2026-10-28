# Local development with PostgreSQL

The API and worker can be run directly on Windows, macOS, or Linux. The database
must be running before migrations or application startup.

## Install dependencies

Install Python 3.11+ and PostgreSQL 16+. On Windows, install PostgreSQL from the
official installer and confirm its service is running in `services.msc`. On Linux,
ensure the PostgreSQL service is started with your distribution's service manager.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

On macOS/Linux, use `python3 -m venv .venv` and `.venv/bin/python` instead.

## Database

Log into pgAdmin Query Tool against the maintenance database (`postgres`) as a
PostgreSQL administrator and execute the following SQL with a unique password:

```sql
CREATE ROLE amrutam_local LOGIN PASSWORD 'CHOOSE_A_STRONG_PASSWORD';
CREATE DATABASE amrutam_local OWNER amrutam_local;
```

Or from `psql`, enter `CREATE ROLE ...` and `CREATE DATABASE ...` separately.
PostgreSQL does not allow `CREATE DATABASE` inside a transaction block.

For an existing project database, **do not run CREATE DATABASE again**. Instead use
its known credentials in `DATABASE_URL`. If you control the existing role but forgot
its database password, an administrator can run
`ALTER ROLE amrutam_local WITH PASSWORD 'NEW_UNIQUE_PASSWORD';`. This changes
credentials only, not stored tables. Never drop tables in an existing project database.

## Environment

Copy `.env.example` to `.env`, for example:

```powershell
Copy-Item .env.example .env
```

Replace the placeholders. `DATABASE_URL` uses a SQLAlchemy PostgreSQL URI:

```text
postgresql+psycopg://amrutam_local:PASSWORD_URL_ENCODED@127.0.0.1:5432/amrutam_local
```

To URL-encode a password safely:

```powershell
.\.venv\Scripts\python.exe -c "from urllib.parse import quote; import getpass; print(quote(getpass.getpass('Database password: '), safe=''))"
```

Generate fresh, independent secrets with the commands below (run the first one
separately for `JWT_SECRET`, `METRICS_TOKEN`, and `ADMIN_PASSWORD`):

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`DATA_ENCRYPTION_KEYS` must be a valid Fernet key. Do not enter an ordinary
password in that field; doing so raises a validation error before migrations.
`RATE_LIMIT_BACKEND=memory` avoids a local Redis dependency for development,
but only enforces limits per API process. Production requires a shared Redis backend.

## Migrate and run

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.bootstrap --skip-existing
.\.venv\Scripts\python.exe scripts\verify_local.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open a second terminal from the same project directory to run:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Use `/health/live` for process health, `/health/ready` for PostgreSQL readiness,
`/docs` for Swagger, and `/openapi.json` for the current API schema.

The first admin login uses `ADMIN_EMAIL` and `ADMIN_PASSWORD`. Sign in, enroll
TOTP using `POST /auth/mfa/enroll`, then confirm with `POST /auth/mfa/confirm`.
Authorize Swagger again with the token returned by MFA confirmation.

## Troubleshooting

| Symptom | Check |
|---|---|
| PostgreSQL host cannot be resolved | Use `127.0.0.1` as the host; never put a password in the host field. |
| Connection refused | Start the PostgreSQL service and check port 5432. |
| PostgreSQL authentication failed | Confirm the database role and password encoded in `DATABASE_URL`. |
| Fernet validation error | Generate a key with `Fernet.generate_key()` and replace `DATA_ENCRYPTION_KEYS`. |
| Database table missing | Run `python -m alembic upgrade head` in the configured virtual environment. |
| Port 8000 in use | Stop the previous Uvicorn process or select another port. |
| Login rejected | Check `ADMIN_EMAIL` / `ADMIN_PASSWORD` and whether the admin already exists. Bootstrap does not overwrite existing passwords. |

The application may be stopped with Ctrl+C. Keep `.env` and database dumps out of
source control and never disclose access tokens or TOTP secrets in issue reports.
