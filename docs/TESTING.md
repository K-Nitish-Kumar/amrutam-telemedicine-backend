# Testing and verification

## Local tests

Install development dependencies from `pyproject.toml`, then run:

```text
python -m pytest -q
python -m compileall -q app alembic tests
```

The default API test suite uses an in-memory SQLite database to keep routine tests
isolated from the application database. It covers authentication, MFA, RBAC,
booking retries and conflicts, prescription encryption, consultation transitions,
payment simulation, admin endpoints, and request validation.

## PostgreSQL integration tests

PostgreSQL-specific constraints and transaction/concurrency semantics must be tested
against PostgreSQL. Set `TEST_POSTGRES_URL` to an **already migrated, disposable** test
database before running `pytest`. Do not use your normal app database.

On Windows PowerShell:

```powershell
$env:TEST_POSTGRES_URL = 'postgresql+psycopg://test_user:URL_ENCODED_PASSWORD@127.0.0.1:5432/amrutam_test'
.\.venv\Scripts\python.exe -m pytest -q
```

The CI workflow provides a PostgreSQL 16 service, runs migrations, and executes the
PostgreSQL integration test. Local PostgreSQL integration tests are skipped without
`TEST_POSTGRES_URL`.

## Static and dependency checks

```text
python -m pip_audit --progress-spinner off
ruff check --select E4,E7,E9,F app tests scripts
```

The GitHub Actions pipeline includes syntax checks, tests, migration checks,
package auditing, and Docker image building. A successful test run does not, by
itself, prove the target latency/availability SLOs; capacity testing, monitoring,
backups, and recovery drills require a deployed environment.

## Load-test reference

`infra/k6.js` is a configurable k6 read profile. Validate on staging with
representative data and realistic concurrency rather than treating a single
laptop run as evidence for 100k daily consultations.
