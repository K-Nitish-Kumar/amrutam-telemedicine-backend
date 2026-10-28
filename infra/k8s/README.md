# Kubernetes deployment example (API only)

Use managed PostgreSQL (PITR + multi-AZ), managed Redis, external ingress with TLS, and your
secret manager. Do NOT deploy raw credentials to Git or run the local PostgreSQL container in
production. Create a Kubernetes Secret named `amrutam-secrets` with keys:
`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `DATA_ENCRYPTION_KEYS`, `METRICS_TOKEN`.

Build and push your reviewed image, replace `registry.example.com/...`, run migrations as a
one-off job before deploying replicas, then apply the YAML. Require TLS/ingress, egress policies,
backup validation, network policies, pod disruption budget, alerts, and provider-specific
hardening before treating this as production-ready.
