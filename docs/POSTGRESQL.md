# PostgreSQL verification

Use pgAdmin 4's Query Tool connected to `amrutam_local`, or `psql` with the
application's database role. These are read-only queries for inspecting demo records.

## Schema and migration

```sql
SELECT version_num FROM alembic_version;
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
```

## Accounts and doctors

```sql
SELECT id, email, role, mfa_enabled FROM users ORDER BY created_at DESC;
SELECT d.id, u.email, d.specialty, d.city, d.verified
FROM doctors d JOIN users u ON u.id = d.user_id ORDER BY u.email;
```

## Availability and consultations

```sql
SELECT id, doctor_id, start_at, end_at, status
FROM availability_slots ORDER BY start_at DESC;
SELECT id, patient_id, doctor_id, slot_id, status, created_at
FROM consultations ORDER BY created_at DESC;
```

## Payments, prescriptions, audit, outbox

```sql
SELECT id, consultation_id, amount_minor, currency, status FROM payments;
SELECT id, consultation_id, issued_by, LEFT(encrypted_document, 25) AS encrypted_prefix
FROM prescriptions;
SELECT action, entity_type, entity_id, created_at
FROM audit_logs ORDER BY created_at DESC LIMIT 20;
SELECT event_type, attempts, processed_at FROM outbox_events
ORDER BY available_at DESC LIMIT 20;
```

**Privacy:** The database queries above are for synthetic data only. Avoid copying
clinical records into logs, screenshots, analytics reports, or bug tickets.

## Backup and restore

Use PostgreSQL's `pg_dump` and `pg_restore`. Run them from your PostgreSQL client
installation; the utility scripts under `scripts/` demonstrate Linux/macOS usage.
A basic custom-format backup is:

```text
pg_dump --format=custom --file=amrutam_local.dump --dbname=amrutam_local
```

Protect backups as sensitive data. Test restores into a **separate** database;
never overwrite a production database while rehearsing disaster recovery.
