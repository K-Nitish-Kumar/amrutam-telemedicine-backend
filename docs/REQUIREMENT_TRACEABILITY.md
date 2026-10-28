# Requirement coverage

The assessment asks for a PostgreSQL-backed telemedicine service plus architecture,
API contract, tests, CI, observability and security analysis.

| Requirement | Implementation | Scope / note |
|---|---|---|
| Backend and infrastructure | `app/`, Dockerfile, Compose, Kubernetes examples | Python REST API; Kubernetes is a deployment reference |
| User lifecycle | Registration, login, profiles, roles, TOTP MFA | Initial admin provisioned via CLI |
| Doctor management | Onboarding, verification, search, slots | Verified doctors shown publicly |
| Booking | Atomic slot claim, idempotency, state transitions | Database concurrency protection |
| Consultations / prescriptions | Care-team access, encrypted document | No live video or clinical validation service |
| Payments | Payment record and demo settlement | No external payment processor |
| Audit / compliance | Append-only PostgreSQL audit trigger, risk analysis | Regulatory signoff is deployment-specific |
| Admin analytics | Aggregate counts, read-only audit browsing | Transactional data; no separate analytics warehouse |
| Observability | JSON request logs, Prometheus metrics, OTLP optional | External monitoring stack not hosted here |
| OpenAPI | `docs/openapi.json`, `/docs`, `/openapi.json` | REST with OpenAPI 3.1 |
| Architectural deliverables | `docs/ARCHITECTURE.md` | Flow, booking sequence, ERD, retry, cache, HA/DR, partition plan |
| Security | `docs/SECURITY.md` | OWASP controls, threat model, encryption/key lifecycle |
| Tests and CI | `tests/`, `.github/workflows/ci.yml` | SQLite unit/API tests + PostgreSQL integration tests |
| Containerized deployment | Docker and `infra/k8s/` | Optional for local development |
| Data partitioning / caching | Architecture document | Design, not a deployed cluster feature |
| 100k/day, p95, 99.95% SLO | Architecture, instrumentation, k6 profile | Targets to validate in a deployed environment |
| Five-minute walkthrough | `docs/DEMO_SCRIPT.md` | Demo outline; video recording is not in the repository |

A working implementation is distinguished from production infrastructure
recommendations and third-party integrations.
