"""PostgreSQL-only tests, automatically enabled in CI via TEST_POSTGRES_URL.

The CI workflow migrates the schema first. Never point this at a real clinical database.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, AvailabilitySlot, Consultation, Doctor, User
from app.security import hash_password


@pytest.mark.skipif(not os.environ.get("TEST_POSTGRES_URL"), reason="PostgreSQL service not configured")
def test_postgres_exclusion_audit_immutability_and_atomic_single_winner():
    engine = create_engine(os.environ["TEST_POSTGRES_URL"], pool_pre_ping=True)
    PgSession = sessionmaker(bind=engine, expire_on_commit=False)
    # Must be migrated by `alembic upgrade head` before this test runs.
    clinician_id, patient_id, doctor_id, slot_id = (uuid.uuid4() for _ in range(4))
    start = datetime.now(timezone.utc) + timedelta(days=8)
    with PgSession.begin() as db:
        db.add_all([
            User(id=clinician_id, email=f"pg-doctor-{clinician_id}@example.test",
                 role="doctor", password_hash=hash_password("integration-only-123")),
            User(id=patient_id, email=f"pg-patient-{patient_id}@example.test",
                 role="patient", password_hash=hash_password("integration-only-123")),
        ])
        db.flush()
        db.add(Doctor(id=doctor_id, user_id=clinician_id, specialty="Ayurveda", city="Hyderabad",
                      license_no=f"PG-TEST-{doctor_id}", fee_minor=10000, verified=True))
        db.flush()
        db.add(AvailabilitySlot(id=slot_id, doctor_id=doctor_id, start_at=start,
                                end_at=start + timedelta(minutes=30), status="open"))

    try:
        # The EXCLUDE constraint rejects a partial overlap even for different start times.
        with pytest.raises(IntegrityError):
            with PgSession.begin() as db:
                db.add(AvailabilitySlot(doctor_id=doctor_id, start_at=start + timedelta(minutes=5),
                                        end_at=start + timedelta(minutes=35), status="open"))

        def race(_):
            with PgSession.begin() as db:
                won = db.execute(update(AvailabilitySlot).where(
                    AvailabilitySlot.id == slot_id, AvailabilitySlot.status == "open"
                ).values(status="booked").returning(AvailabilitySlot.id)).scalar_one_or_none()
                if won:
                    db.add(Consultation(patient_id=patient_id, doctor_id=doctor_id,
                                        slot_id=slot_id, fee_minor=10000))
            return won is not None

        with ThreadPoolExecutor(max_workers=4) as pool:
            winners = list(pool.map(race, range(4)))
        assert sum(winners) == 1
        with PgSession() as db:
            assert db.scalar(select(func.count()).select_from(Consultation).where(
                Consultation.slot_id == slot_id)) == 1

        # Audit updates must fail even when performed via raw SQL; no mutable clinical metadata.
        with PgSession() as db:
            event = AuditLog(actor_id=clinician_id, action="pg.test", entity_type="doctors",
                             entity_id=str(doctor_id), meta={})
            db.add(event)
            db.flush()
            with pytest.raises(DBAPIError):
                with db.begin_nested():
                    db.execute(update(AuditLog).where(AuditLog.id == event.id).values(action="tamper"))
            db.rollback()
    finally:
        with PgSession.begin() as db:
            db.query(Consultation).filter(Consultation.slot_id == slot_id).delete()
            db.query(AvailabilitySlot).filter(AvailabilitySlot.doctor_id == doctor_id).delete()
            db.query(Doctor).filter(Doctor.id == doctor_id).delete()
            db.query(User).filter(User.id.in_([clinician_id, patient_id])).delete()
        engine.dispose()
