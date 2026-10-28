.\.venv\Scripts\python.exe -m pip install --upgrade pip# Amrutam Telemedicine Backend

Python/FastAPI REST API for patient onboarding, doctor availability, appointment booking,
consultations, prescriptions, payment records, and administrative operations. PostgreSQL
provides the primary transactional datastore; Redis is optional for local development.

## Scope

- User registration and authentication with Argon2id password hashing and signed JWTs
- Role-based access control for patients, doctors, and administrators; TOTP MFA for privileged access
- Doctor onboarding, verification, directory search, and availability management
- Transactional booking with `Idempotency-Key` and atomic slot claiming
- Consultation state transitions, encrypted prescriptions, and patient/doctor access checks
- Payment records with a **local test adapter** (no actual payment processing)
- Audit events, transactional outbox worker, admin analytics, request metrics, logs, and optional traces
- Alembic migrations, OpenAPI 3.1, tests, CI, and infrastructure examples

This repository implements an **API**, not a patient-facing website. Interactive API
exploration is provided at `http://127.0.0.1:8000/docs`.

## Requirements

- Python 3.11+ and pip
- PostgreSQL 16+ running locally (default port 5432)
- Git for version control
- Optional: Redis for distributed rate limiting; Docker/Kubernetes for deployment examples

**Docker is not required for local development.** Local setup uses standard Python and SQL commands.

## Local setup (Windows PowerShell)

Run the commands from the project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
```

Create a PostgreSQL role and database using pgAdmin Query Tool connected as the
`postgres` administrator (or via `psql`). Choose a unique password and do not reuse a
PostgreSQL administrator password for the app:

```sql
CREATE ROLE amrutam_local WITH LOGIN PASSWORD 'YOUR_STRONG_DATABASE_PASSWORD';
CREATE DATABASE amrutam_local OWNER amrutam_local;
```

Run each PostgreSQL statement separately. If the role/database already exist, **do not recreate or drop them**. Reuse their existing
credentials or explicitly rotate the role password with an authorized administrator.
See [local development](docs/LOCAL_DEVELOPMENT.md) for the existing-database case and macOS/Linux.

Copy `.env.example` to `.env` and configure `DATABASE_URL`, `JWT_SECRET`,
`DATA_ENCRYPTION_KEYS`, `METRICS_TOKEN`, and `ADMIN_PASSWORD` with your own values.
To generate independent cryptographic secrets, run:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use the first command to generate a JWT secret and repeat it to generate an independent
metrics token and admin password. Use the second command for `DATA_ENCRYPTION_KEYS`.
URL-encode special characters in database passwords (for example `@` becomes `%40`).
Do not commit `.env`.

Apply database migrations and create the initial admin:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.bootstrap --skip-existing
.\.venv\Scripts\python.exe scripts\verify_local.py
```

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second PowerShell terminal, start the outbox worker:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Open `http://127.0.0.1:8000/docs` for Swagger UI. `/health/ready` verifies the
database connection. Local `RATE_LIMIT_BACKEND=memory` needs no Redis service.

## Authentication and example walkthrough

1. Create a patient or doctor account with `POST /auth/register` (the default role is patient).
2. Sign in with `POST /auth/login`. The first admin login returns an access token with
   `mfa_setup_required=true`. Authorize Swagger with this bearer token, call
   `POST /auth/mfa/enroll`, and register the returned TOTP secret in an authenticator app.
3. Confirm the six-digit code via `POST /auth/mfa/confirm`. **Replace** the Swagger token
   with the **new** access token. Subsequent admin/doctor logins use a challenge token
   and `POST /auth/mfa/verify-login` to complete MFA.
4. As admin, onboard/verify a doctor using `POST /admin/doctors`. The doctor's user must
   already exist. Sign in as that doctor and complete MFA.
5. As doctor, create a future availability window with `POST /doctors/{doctor_id}/slots`
   and a unique `Idempotency-Key` header (8–128 characters).
6. As patient, search `GET /doctors`, find availability via
   `GET /doctors/{doctor_id}/slots`, and reserve with `POST /bookings`, supplying the
   slot UUID and an idempotency key. Repeating the same request with the same key is safe.
7. Check `GET /consultations/{id}/payment`. In local demo mode only,
   `POST /payments/{payment_id}/demo-settle` simulates settlement; no funds are transferred.
8. As doctor, transition the consultation to `in_progress`, issue a prescription,
   then transition it to `completed`. As patient, view the consultation and prescription.
9. As admin, inspect `GET /admin/analytics` and `GET /admin/audit-logs`.

See [API behavior](docs/API_BEHAVIOR.md) for authorization rules, state transitions,
errors, and idempotency. [Database verification](docs/POSTGRESQL.md) provides read-only
SQL queries for inspecting test records.

## Quality checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q app alembic tests
.\.venv\Scripts\python.exe -m pip_audit --progress-spinner off
```

Tests are isolated by default and do not modify your configured PostgreSQL database.
The PostgreSQL integration test runs only when `TEST_POSTGRES_URL` points to a
**disposable, migrated test database**. See [testing](docs/TESTING.md).

To refresh the committed OpenAPI file after modifying routes:

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
```

## Deployment and operations

The repository includes a Dockerfile, Docker Compose specification, Kubernetes manifests,
Prometheus configuration, and GitHub Actions CI. These support containerized deployment;
none is required for local Windows development. Production operation requires a managed
PostgreSQL service, distributed rate limiting, TLS, backups, secret management, and
independent security/performance reviews.

**Production limitations:** The demo payment adapter is not a payment gateway; the
background outbox worker demonstrates event processing but has no email/SMS provider.
No video consultation UI or actual clinical approval workflow is included. Scaling to
100k daily consultations, read/write p95 targets, and 99.95% availability are **design
objectives**, not tested service guarantees. Never use demo mode with real patient data.

## Project layout

```text
app/                     API routes, services, domain models, security, background worker
alembic/                 Versioned database migrations
scripts/                 OpenAPI export, smoke check, environment check, backup utilities
tests/                   API, security, configuration and PostgreSQL integration tests
docs/                    Architecture, threat model, API behavior, local setup, testing, demo
infra/                   Performance profile, Prometheus and Kubernetes examples
.github/workflows/       CI pipeline
Dockerfile               Container build
pyproject.toml           Python dependencies and tooling configuration
.env.example             Configuration template (contains no usable secrets)
```

## Documentation

- [Architecture and data flow](docs/ARCHITECTURE.md)
- [Security checklist and threat model](docs/SECURITY.md)
- [API contract](docs/API_BEHAVIOR.md) and [OpenAPI specification](docs/openapi.json)
- [Local development](docs/LOCAL_DEVELOPMENT.md)
- [PostgreSQL verification](docs/POSTGRESQL.md)
- [Testing and CI](docs/TESTING.md)
- [Requirements coverage](docs/REQUIREMENT_TRACEABILITY.md)
- [5-minute demo outline](docs/DEMO_SCRIPT.md)

## GitHub

Create an empty GitHub repository, then commit the **source** files:

```text
git init
git add .
git commit -m "Implement telemedicine backend API"
git branch -M main
git remote add origin https://github.com/<account>/<repository>.git
git push -u origin main
```

`.env`, `.venv`, database dumps, and other local files are ignored by `.gitignore`.
Inspect `git status` before pushing to ensure that no credentials are staged.
