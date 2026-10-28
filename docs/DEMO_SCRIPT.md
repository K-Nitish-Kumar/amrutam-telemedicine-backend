# Suggested five-minute live demo recording outline

The assignment asks for a five-minute demo video. No video file is bundled; use this outline
to record your **own running local application** in the Swagger console. This document avoids
claiming a live recording exists.

| Time | On-screen walkthrough | Why it matters |
|---|---|---|
| 0:00–0:35 | Start Uvicorn with `python -m uvicorn app.main:app`, show `/health/ready`, `/docs` and PostgreSQL tables with pgAdmin | local runnable app, real PostgreSQL |
| 0:35–1:15 | Admin login, TOTP enrollment + confirmation, create verified doctor | auth/RBAC/MFA workflow |
| 1:15–1:55 | Doctor login + MFA; create a future slot, search directory | availability, validation, search |
| 1:55–2:40 | Patient signup and booking; repeat request with same `Idempotency-Key`, show same ID; try second patient booking, see 409 | concurrency and replay safety |
| 2:40–3:20 | Retrieve pending payment, demo settle, move consultation `in_progress` | payment record and lifecycle |
| 3:20–4:00 | Doctor creates prescription; patient reads it; demonstrate unauthorized second patient 403 | encryption and access controls |
| 4:00–4:35 | Admin analytics and audit trails; `/metrics` token-protected, logs show no PHI | observability, compliance |
| 4:35–5:00 | Open `docs/ARCHITECTURE.md`, show sequence/ER, CI/tests and explain production limitations | complete deliverables and tradeoffs |

For a smooth recording, prepare a TOTP app and use dates 2–3 days in the future.
Do not display real patient data, secrets, JWTs, MFA seeds or your `.env` onscreen.
