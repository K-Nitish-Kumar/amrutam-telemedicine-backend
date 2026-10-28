import uuid
from datetime import date, datetime, time, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.deps import current_user, require_roles
from app.models import (
    AuditLog, AvailabilitySlot, Consultation, Doctor, Payment, Prescription, Profile, User,
)
from app.schemas import (
    BookingCreate, ConsultationResponse, DoctorCreate, DoctorResponse, Login, MFAChallenge, MFACode,
    MessageResponse, PaymentResponse, PrescriptionCreate, PrescriptionResponse,
    ProfileUpdate, Registration, SlotCreate, SlotResponse, StatusUpdate, TokenResponse, UserResponse,
)
from app.security import (
    check_password, create_token, decode_token, decrypt_json, decrypt_string,
    encrypt_json, encrypt_string, hash_password, new_totp_secret, totp_enrollment_uri,
    verify_totp_step,
)
from app.services import (
    audit, forbidden, idempotency_replay, idempotency_save, not_found, outbox, utc_aware,
)

router = APIRouter()


def write(db: Session, detail: str = "Conflict; check existing resources"):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from None


def get_doctor(db: Session, user: User) -> Doctor:
    doctor = db.scalar(select(Doctor).where(Doctor.user_id == user.id))
    if not doctor:
        not_found("Doctor profile")
    return doctor


def is_care_team(db: Session, consultation: Consultation, user: User) -> bool:
    if consultation.patient_id == user.id:
        return True
    return bool(db.scalar(select(Doctor.id).where(Doctor.id == consultation.doctor_id,
                                                      Doctor.user_id == user.id)))


def check_care_team(db: Session, consultation: Consultation, user: User):
    if not is_care_team(db, consultation, user):
        forbidden()


def render_prescription(item: Prescription) -> PrescriptionResponse:
    doc = decrypt_json(item.encrypted_document)
    return PrescriptionResponse(id=item.id, consultation_id=item.consultation_id,
                                issued_by=item.issued_by, created_at=item.created_at,
                                document=PrescriptionCreate.model_validate(doc))


@router.post("/auth/register", response_model=UserResponse, status_code=201, tags=["Auth"])
def register(body: Registration, db: Session = Depends(get_db)):
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account already exists") from None
    db.add(Profile(user_id=user.id, full_name=body.full_name))
    audit(db, user.id, "user.registered", "users", user.id)
    write(db, "Account already exists")
    return user


@router.post("/auth/login", tags=["Auth"])
def login(body: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    # Always run a password verification even for unknown accounts to reduce enumeration timing.
    if user:
        valid = check_password(body.password, user.password_hash)
    else:
        valid = check_password(body.password, _DUMMY_PASSWORD_HASH)
    if not user or not user.is_active or not valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.mfa_enabled:
        return {"mfa_required": True, "challenge_token": create_token(user.id, kind="mfa", ttl_minutes=5)}
    return {"mfa_required": False, "access_token": create_token(user.id), "token_type": "bearer",
            "mfa_setup_required": user.role in ("admin", "doctor")}


# Stable generated sample Argon2 hash; never use it as a real user credential.
_DUMMY_PASSWORD_HASH = hash_password("not_a_real_account_password_for_timing")


@router.post("/auth/mfa/enroll", tags=["Auth"])
def enroll_mfa(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA already enabled; contact administrator to reset")
    secret = new_totp_secret()
    user.mfa_secret_enc = encrypt_string(secret)
    audit(db, user.id, "mfa.enrollment_started", "users", user.id)
    write(db)
    # Only display secret here, once. Never log or store plaintext TOTP seeds.
    return {"secret": secret, "otpauth_uri": totp_enrollment_uri(user.email, secret)}


@router.post("/auth/mfa/confirm", response_model=TokenResponse, tags=["Auth"])
def confirm_mfa(body: MFACode, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.mfa_enabled or not user.mfa_secret_enc:
        raise HTTPException(status_code=400, detail="No pending MFA enrollment")
    step = verify_totp_step(decrypt_string(user.mfa_secret_enc), body.code, user.last_totp_step)
    if step is None:
        raise HTTPException(status_code=401, detail="Invalid authenticator code")
    user.last_totp_step = step
    user.mfa_enabled = True
    audit(db, user.id, "mfa.enabled", "users", user.id)
    write(db)
    return {"access_token": create_token(user.id, mfa_verified=True), "token_type": "bearer"}


@router.post("/auth/mfa/verify-login", response_model=TokenResponse, tags=["Auth"])
def verify_mfa_login(body: MFAChallenge, db: Session = Depends(get_db)):
    try:
        user_id = decode_token(body.challenge_token, kind="mfa")
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired MFA challenge") from None
    user = db.get(User, user_id, with_for_update=True)
    if not user or not user.is_active or not user.mfa_enabled or not user.mfa_secret_enc:
        raise HTTPException(status_code=401, detail="MFA challenge invalid")
    step = verify_totp_step(decrypt_string(user.mfa_secret_enc), body.code, user.last_totp_step)
    if step is None:
        raise HTTPException(status_code=401, detail="Invalid or previously used code")
    user.last_totp_step = step
    audit(db, user.id, "mfa.login", "users", user.id)
    write(db)
    return {"access_token": create_token(user.id, mfa_verified=True), "token_type": "bearer"}


@router.get("/me", response_model=UserResponse, tags=["Users"])
def me(user: User = Depends(current_user)):
    return user


@router.get("/me/profile", tags=["Users"])
def my_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    return {"full_name": profile.full_name, "phone": profile.phone} if profile else {}


@router.put("/me/profile", tags=["Users"])
def update_profile(body: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if not profile:
        profile = Profile(user_id=user.id, full_name=body.full_name)
        db.add(profile)
    profile.full_name = body.full_name
    profile.phone = body.phone
    db.flush()
    audit(db, user.id, "profile.updated", "profiles", profile.id)
    write(db)
    return {"full_name": profile.full_name, "phone": profile.phone}


@router.post("/admin/doctors", response_model=DoctorResponse, status_code=201, tags=["Admin"])
def create_doctor(body: DoctorCreate, admin: User = Depends(require_roles("admin")),
                  db: Session = Depends(get_db)):
    target = db.scalar(select(User).where(User.email == body.user_email.strip().lower()).with_for_update())
    if not target:
        not_found("Registered user")
    if target.role != "patient":
        raise HTTPException(status_code=409, detail="User is already privileged")
    doctor = Doctor(user_id=target.id, license_no=body.license_no, specialty=body.specialty,
                    city=body.city, bio=body.bio, fee_minor=body.fee_minor, verified=body.verified)
    target.role = "doctor"
    db.add(doctor)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Doctor license or profile already exists") from None
    audit(db, admin.id, "doctor.created", "doctors", doctor.id, {"verified": body.verified})
    write(db, "Doctor license or profile already exists")
    return doctor


@router.get("/doctors", response_model=list[DoctorResponse], tags=["Doctors"])
def list_doctors(specialty: str | None = Query(default=None, max_length=100),
                 city: str | None = Query(default=None, max_length=100),
                 available_on: date | None = None,
                 limit: int = Query(default=20, ge=1, le=100),
                 offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    stmt = select(Doctor).options(joinedload(Doctor.user).joinedload(User.profile)).where(Doctor.verified.is_(True))
    if specialty:
        stmt = stmt.where(Doctor.specialty.ilike(f"%{escape_like(specialty)}%", escape="\\"))
    if city:
        stmt = stmt.where(Doctor.city.ilike(f"%{escape_like(city)}%", escape="\\"))
    if available_on:
        start = datetime.combine(available_on, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        stmt = stmt.where(select(AvailabilitySlot.id).where(
            AvailabilitySlot.doctor_id == Doctor.id, AvailabilitySlot.status == "open",
            AvailabilitySlot.start_at >= start, AvailabilitySlot.start_at < end).exists())
    return db.scalars(stmt.order_by(Doctor.specialty, Doctor.id).limit(limit).offset(offset)).all()


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/doctors/{doctor_id}", response_model=DoctorResponse, tags=["Doctors"])
def show_doctor(doctor_id: uuid.UUID, db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor or not doctor.verified:
        not_found("Doctor")
    return doctor


@router.post("/doctors/{doctor_id}/slots", response_model=SlotResponse, status_code=201, tags=["Doctors"])
def create_slot(doctor_id: uuid.UUID, body: SlotCreate,
                idem_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
                actor: User = Depends(require_roles("admin", "doctor")),
                db: Session = Depends(get_db)):
    doc = db.get(Doctor, doctor_id)
    if not doc:
        not_found("Doctor")
    if actor.role == "doctor" and doc.user_id != actor.id:
        forbidden()
    start, end = body.start_at.astimezone(timezone.utc), body.end_at.astimezone(timezone.utc)
    replay_id, fingerprint = idempotency_replay(db, actor.id, "slot.create", idem_key,
                                                  {"doctor_id": doctor_id, "start": start, "end": end})
    if replay_id:
        item = db.get(AvailabilitySlot, replay_id)
        db.commit()
        return item
    if start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Availability must be in the future")
    # User-friendly pre-check; PostgreSQL EXCLUDE constraint is authoritative under concurrency.
    overlap = db.scalar(select(AvailabilitySlot.id).where(
        AvailabilitySlot.doctor_id == doc.id, AvailabilitySlot.start_at < end,
        AvailabilitySlot.end_at > start).limit(1))
    if overlap:
        raise HTTPException(status_code=409, detail="Availability overlaps an existing slot")
    slot = AvailabilitySlot(doctor_id=doc.id, start_at=start, end_at=end)
    db.add(slot)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting or overlapping availability") from None
    idempotency_save(db, actor.id, "slot.create", idem_key, fingerprint, slot.id)
    audit(db, actor.id, "slot.created", "availability_slots", slot.id)
    write(db, "Conflicting or overlapping availability")
    return slot


@router.get("/doctors/{doctor_id}/slots", response_model=list[SlotResponse], tags=["Doctors"])
def list_slots(doctor_id: uuid.UUID, on_date: date | None = None,
               limit: int = Query(default=100, ge=1, le=100), db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor or not doctor.verified:
        not_found("Doctor")
    stmt = select(AvailabilitySlot).where(AvailabilitySlot.doctor_id == doctor_id,
                                           AvailabilitySlot.status == "open",
                                           AvailabilitySlot.start_at > datetime.now(timezone.utc))
    if on_date:
        start = datetime.combine(on_date, time.min, tzinfo=timezone.utc)
        stmt = stmt.where(AvailabilitySlot.start_at >= start,
                          AvailabilitySlot.start_at < start + timedelta(days=1))
    return db.scalars(stmt.order_by(AvailabilitySlot.start_at).limit(limit)).all()


@router.post("/bookings", response_model=ConsultationResponse, status_code=201, tags=["Consultations"])
def book(body: BookingCreate,
         idem_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
         actor: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    replay_id, fingerprint = idempotency_replay(db, actor.id, "consultation.book", idem_key,
                                                  body.model_dump(mode="json"))
    if replay_id:
        consultation = db.get(Consultation, replay_id)
        db.commit()
        return consultation
    # Atomic compare-and-set: only one transaction can switch open -> booked.
    slot = db.get(AvailabilitySlot, body.slot_id)
    if not slot:
        not_found("Slot")
    if utc_aware(slot.start_at) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Cannot book past availability")
    doctor = db.get(Doctor, slot.doctor_id)
    if not doctor or not doctor.verified:
        raise HTTPException(status_code=409, detail="Doctor is not verified")
    changed = db.execute(update(AvailabilitySlot).where(
        AvailabilitySlot.id == slot.id, AvailabilitySlot.status == "open"
    ).values(status="booked").returning(AvailabilitySlot.id)).scalar_one_or_none()
    if changed is None:
        raise HTTPException(status_code=409, detail="Slot is already booked")
    consultation = Consultation(patient_id=actor.id, doctor_id=doctor.id, slot_id=slot.id,
                                fee_minor=doctor.fee_minor)
    db.add(consultation)
    db.flush()
    db.add(Payment(consultation_id=consultation.id, patient_id=actor.id, amount_minor=doctor.fee_minor))
    idempotency_save(db, actor.id, "consultation.book", idem_key, fingerprint, consultation.id)
    audit(db, actor.id, "consultation.booked", "consultations", consultation.id)
    outbox(db, "consultation.booked", {"consultation_id": str(consultation.id)})
    write(db, "Booking conflict; slot may already be reserved")
    return consultation


@router.get("/consultations", response_model=list[ConsultationResponse], tags=["Consultations"])
def my_consultations(actor: User = Depends(require_roles("patient", "doctor")),
                     limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0),
                     db: Session = Depends(get_db)):
    stmt = select(Consultation)
    if actor.role == "patient":
        stmt = stmt.where(Consultation.patient_id == actor.id)
    else:
        doctor = get_doctor(db, actor)
        stmt = stmt.where(Consultation.doctor_id == doctor.id)
    return db.scalars(stmt.order_by(Consultation.created_at.desc()).limit(limit).offset(offset)).all()


@router.get("/consultations/{consultation_id}", response_model=ConsultationResponse,
            tags=["Consultations"])
def view_consultation(consultation_id: uuid.UUID, actor: User = Depends(require_roles("patient", "doctor")),
                      db: Session = Depends(get_db)):
    consultation = db.get(Consultation, consultation_id)
    if not consultation:
        not_found("Consultation")
    check_care_team(db, consultation, actor)
    return consultation


@router.patch("/consultations/{consultation_id}/status", response_model=ConsultationResponse,
              tags=["Consultations"])
def change_status(consultation_id: uuid.UUID, body: StatusUpdate,
                  actor: User = Depends(require_roles("patient", "doctor")), db: Session = Depends(get_db)):
    consultation = db.scalar(select(Consultation).where(Consultation.id == consultation_id).with_for_update())
    if not consultation:
        not_found("Consultation")
    check_care_team(db, consultation, actor)
    doctor_user_id = db.scalar(select(Doctor.user_id).where(Doctor.id == consultation.doctor_id))
    is_doctor = actor.id == doctor_user_id
    before, target = consultation.status, body.status
    if target == "cancelled":
        if before != "booked":
            raise HTTPException(status_code=409, detail="Only booked consultations can be cancelled")
        slot = db.get(AvailabilitySlot, consultation.slot_id, with_for_update=True)
        if utc_aware(slot.start_at) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="Too late to cancel the booking")
        slot.status = "open"
        payment = db.scalar(select(Payment).where(Payment.consultation_id == consultation.id).with_for_update())
        if payment:
            payment.status = "refund_pending" if payment.status == "paid" else "void"
    elif target == "in_progress" and before == "booked" and is_doctor:
        pass
    elif target == "completed" and before == "in_progress" and is_doctor:
        pass
    else:
        raise HTTPException(status_code=409, detail="Invalid lifecycle transition or role")
    consultation.status = target
    audit(db, actor.id, "consultation.status_changed", "consultations", consultation.id,
          {"from": before, "to": target})
    outbox(db, "consultation.status_changed", {"consultation_id": str(consultation.id), "status": target})
    write(db)
    return consultation


@router.post("/consultations/{consultation_id}/prescriptions", response_model=PrescriptionResponse,
             status_code=201, tags=["Prescriptions"])
def create_prescription(consultation_id: uuid.UUID, body: PrescriptionCreate,
                        idem_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
                        actor: User = Depends(require_roles("doctor")), db: Session = Depends(get_db)):
    consultation = db.get(Consultation, consultation_id)
    if not consultation:
        not_found("Consultation")
    doctor = get_doctor(db, actor)
    if consultation.doctor_id != doctor.id:
        forbidden()
    if consultation.status not in ("in_progress", "completed"):
        raise HTTPException(status_code=409, detail="Consultation must be started")
    replay_id, fingerprint = idempotency_replay(db, actor.id, "prescription.create", idem_key,
        {"consultation_id": str(consultation_id), **body.model_dump(mode="json")})
    if replay_id:
        prescription = db.get(Prescription, replay_id)
        db.commit()
        return render_prescription(prescription)
    prescription = Prescription(consultation_id=consultation.id, issued_by=actor.id,
                                encrypted_document=encrypt_json(body.model_dump(mode="json")))
    db.add(prescription)
    db.flush()
    idempotency_save(db, actor.id, "prescription.create", idem_key, fingerprint, prescription.id)
    audit(db, actor.id, "prescription.created", "prescriptions", prescription.id)
    outbox(db, "prescription.created", {"prescription_id": str(prescription.id)})
    write(db)
    return render_prescription(prescription)


@router.get("/consultations/{consultation_id}/prescriptions", response_model=list[PrescriptionResponse],
            tags=["Prescriptions"])
def list_prescriptions(consultation_id: uuid.UUID,
                       actor: User = Depends(require_roles("patient", "doctor")), db: Session = Depends(get_db)):
    consultation = db.get(Consultation, consultation_id)
    if not consultation:
        not_found("Consultation")
    check_care_team(db, consultation, actor)
    return [render_prescription(p) for p in db.scalars(select(Prescription).where(
        Prescription.consultation_id == consultation_id).order_by(Prescription.created_at)).all()]


@router.get("/consultations/{consultation_id}/payment", response_model=PaymentResponse, tags=["Payments"])
def get_payment(consultation_id: uuid.UUID, actor: User = Depends(require_roles("patient", "doctor")),
                db: Session = Depends(get_db)):
    consultation = db.get(Consultation, consultation_id)
    if not consultation:
        not_found("Consultation")
    check_care_team(db, consultation, actor)
    payment = db.scalar(select(Payment).where(Payment.consultation_id == consultation.id))
    if not payment:
        not_found("Payment")
    return payment


@router.post("/payments/{payment_id}/demo-settle", response_model=PaymentResponse, tags=["Payments"])
def demo_settle(payment_id: uuid.UUID,
                idem_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
                actor: User = Depends(require_roles("patient")), db: Session = Depends(get_db)):
    if get_settings().payments_mode != "demo":
        raise HTTPException(status_code=403, detail="Demo payment adapter is disabled")
    replay_id, fingerprint = idempotency_replay(db, actor.id, "payment.demo-settle", idem_key,
                                                  {"payment_id": payment_id})
    if replay_id:
        payment = db.get(Payment, replay_id)
        db.commit()
        return payment
    payment = db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if not payment:
        not_found("Payment")
    if payment.patient_id != actor.id:
        forbidden()
    if payment.status != "pending":
        raise HTTPException(status_code=409, detail="Payment cannot be settled")
    payment.status = "paid"
    payment.provider_reference = f"demo-{uuid.uuid4()}"
    idempotency_save(db, actor.id, "payment.demo-settle", idem_key, fingerprint, payment.id)
    audit(db, actor.id, "payment.demo_paid", "payments", payment.id)
    outbox(db, "payment.demo_paid", {"payment_id": str(payment.id)})
    write(db)
    return payment


@router.get("/admin/analytics", tags=["Admin"])
def analytics(admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    # Aggregated data only; never expose patient medical records here.
    counts = dict(db.execute(select(Consultation.status, func.count()).group_by(Consultation.status)).all())
    paid_sum = db.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(Payment.status == "paid"))
    return {"consultations_by_status": counts,
            "total_consultations": sum(counts.values()),
            "verified_doctors": db.scalar(select(func.count()).select_from(Doctor).where(Doctor.verified.is_(True))),
            "registered_patients": db.scalar(select(func.count()).select_from(User).where(User.role == "patient")),
            "demo_or_external_paid_minor": paid_sum, "currency": "INR"}


@router.get("/admin/audit-logs", tags=["Admin"])
def list_audit(admin: User = Depends(require_roles("admin")),
               limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
               db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"id": x.id, "actor_id": x.actor_id, "action": x.action, "entity_type": x.entity_type,
             "entity_id": x.entity_id, "meta": x.meta, "created_at": x.created_at} for x in rows]


@router.post("/admin/users/{user_id}/deactivate", response_model=MessageResponse, tags=["Admin"])
def deactivate_user(user_id: uuid.UUID, admin: User = Depends(require_roles("admin")),
                    db: Session = Depends(get_db)):
    if user_id == admin.id:
        raise HTTPException(status_code=409, detail="Cannot disable your own admin account")
    target = db.get(User, user_id, with_for_update=True)
    if not target:
        not_found("User")
    if target.is_active:
        target.is_active = False
        audit(db, admin.id, "user.deactivated", "users", user_id)
        write(db)
    return {"message": "Account disabled"}


@router.post("/admin/doctors/{doctor_id}/verify", response_model=DoctorResponse, tags=["Admin"])
def verify_doctor(doctor_id: uuid.UUID, admin: User = Depends(require_roles("admin")),
                  db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id, with_for_update=True)
    if not doctor:
        not_found("Doctor")
    if not doctor.verified:
        doctor.verified = True
        audit(db, admin.id, "doctor.verified", "doctors", doctor.id)
        write(db)
    return doctor


@router.patch("/doctors/{doctor_id}/slots/{slot_id}/block", response_model=SlotResponse,
              tags=["Doctors"])
def block_slot(doctor_id: uuid.UUID, slot_id: uuid.UUID,
               actor: User = Depends(require_roles("admin", "doctor")),
               db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        not_found("Doctor")
    if actor.role == "doctor" and doctor.user_id != actor.id:
        forbidden()
    slot = db.get(AvailabilitySlot, slot_id, with_for_update=True)
    if not slot or slot.doctor_id != doctor.id:
        not_found("Slot")
    if slot.status == "booked":
        raise HTTPException(status_code=409, detail="Booked slots cannot be blocked")
    if slot.status != "blocked":
        slot.status = "blocked"
        audit(db, actor.id, "slot.blocked", "availability_slots", slot.id)
        write(db)
    return slot
