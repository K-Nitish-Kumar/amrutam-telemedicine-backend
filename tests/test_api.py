import uuid
from datetime import datetime, timedelta, timezone

from app.models import AuditLog, Consultation, Prescription, Profile, User
from app.security import hash_password, totp_for_step
from app import security


PASSWORD = "AValidPassword12345!"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(client, email, name="Test User"):
    result = client.post("/auth/register", json={"email": email, "password": PASSWORD, "full_name": name})
    assert result.status_code == 201, result.text
    result = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200
    return result.json()["access_token"]


def setup_mfa(client, token):
    enroll = client.post("/auth/mfa/enroll", headers=auth(token))
    assert enroll.status_code == 200, enroll.text
    secret = enroll.json()["secret"]
    step = int(security.time.time()) // 30
    confirm = client.post("/auth/mfa/confirm", json={"code": totp_for_step(secret, step)}, headers=auth(token))
    assert confirm.status_code == 200, confirm.text
    return secret, confirm.json()["access_token"]


def create_doctor_and_admin(client, db):
    doc_token = register(client, "doctor@example.test", "Doctor Test")
    admin = User(email="admin@example.test", role="admin", password_hash=hash_password(PASSWORD))
    db.add(admin)
    db.flush()
    db.add(Profile(user_id=admin.id, full_name="Administrator"))
    db.commit()
    admin_login = client.post("/auth/login", json={"email": "admin@example.test", "password": PASSWORD})
    admin_token = admin_login.json()["access_token"]
    assert client.get("/admin/analytics", headers=auth(admin_token)).status_code == 403
    admin_secret, admin_token = setup_mfa(client, admin_token)
    result = client.post("/admin/doctors", headers=auth(admin_token), json={
        "user_email": "doctor@example.test", "license_no": "TEST-LICENSE-1056",
        "specialty": "Ayurveda", "city": "Hyderabad", "fee_minor": 75000, "verified": True,
    })
    assert result.status_code == 201, result.text
    doctor_id = result.json()["id"]
    assert client.get("/consultations", headers=auth(doc_token)).status_code == 403
    doctor_secret, doc_token = setup_mfa(client, doc_token)
    return doc_token, admin_token, doctor_id, doctor_secret, admin_secret


def add_slot(client, doctor_id, doc_token, key="slot-first"):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    end = start + timedelta(minutes=30)
    payload = {"start_at": start.isoformat(), "end_at": end.isoformat()}
    result = client.post(f"/doctors/{doctor_id}/slots", json=payload,
                         headers={**auth(doc_token), "Idempotency-Key": key})
    assert result.status_code == 201, result.text
    return result.json()["id"], payload


def test_full_consultation_booking_prescription_payment_and_security(client, db):
    doctor_token, admin_token, doctor_id, _, _ = create_doctor_and_admin(client, db)
    patient_token = register(client, "patient1@example.test", "Patient One")
    other_patient_token = register(client, "patient2@example.test", "Patient Two")
    slot_id, slot_payload = add_slot(client, doctor_id, doctor_token)
    assert client.get("/doctors", params={"specialty": "ayu", "city": "hyd"}).json()[0]["id"] == doctor_id
    assert len(client.get(f"/doctors/{doctor_id}/slots").json()) == 1
    repeat_slot = client.post(f"/doctors/{doctor_id}/slots", json=slot_payload,
                              headers={**auth(doctor_token), "Idempotency-Key": "slot-first"})
    assert repeat_slot.status_code == 201
    assert repeat_slot.json()["id"] == slot_id
    booking_headers = {**auth(patient_token), "Idempotency-Key": "booking-A-0001"}
    first = client.post("/bookings", json={"slot_id": slot_id}, headers=booking_headers)
    assert first.status_code == 201, first.text
    consultation_id = first.json()["id"]
    retry = client.post("/bookings", json={"slot_id": slot_id}, headers=booking_headers)
    assert retry.status_code == 201 and retry.json()["id"] == consultation_id
    collision = client.post("/bookings", json={"slot_id": str(uuid.uuid4())}, headers=booking_headers)
    assert collision.status_code == 409
    conflict = client.post("/bookings", json={"slot_id": slot_id},
                           headers={**auth(other_patient_token), "Idempotency-Key": "booking-B-0001"})
    assert conflict.status_code == 409
    hidden = client.get(f"/consultations/{consultation_id}", headers=auth(other_patient_token))
    assert hidden.status_code == 403
    assert client.patch(f"/consultations/{consultation_id}/status", json={"status": "completed"},
                        headers=auth(patient_token)).status_code == 409
    payment = client.get(f"/consultations/{consultation_id}/payment", headers=auth(patient_token))
    assert payment.status_code == 200
    paid = client.post(f"/payments/{payment.json()['id']}/demo-settle",
                       headers={**auth(patient_token), "Idempotency-Key": "payment-00001"})
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    assert client.post(f"/payments/{payment.json()['id']}/demo-settle",
                       headers={**auth(patient_token), "Idempotency-Key": "payment-00001"}).status_code == 200
    started = client.patch(f"/consultations/{consultation_id}/status", json={"status": "in_progress"},
                           headers=auth(doctor_token))
    assert started.status_code == 200, started.text
    rx = {"medications": [{"name": "Herbal Medicine", "dosage": "1 tablet",
                           "frequency": "Once daily", "duration_days": 7}], "instructions": "After a meal"}
    created = client.post(f"/consultations/{consultation_id}/prescriptions", json=rx,
                          headers={**auth(doctor_token), "Idempotency-Key": "rx-key-0001"})
    assert created.status_code == 201, created.text
    assert created.json()["document"] == rx
    assert client.post(f"/consultations/{consultation_id}/prescriptions", json=rx,
                       headers={**auth(doctor_token), "Idempotency-Key": "rx-key-0001"}).json()["id"] == created.json()["id"]
    assert client.get(f"/consultations/{consultation_id}/prescriptions",
                      headers=auth(other_patient_token)).status_code == 403
    assert len(client.get(f"/consultations/{consultation_id}/prescriptions",
                          headers=auth(patient_token)).json()) == 1
    assert client.patch(f"/consultations/{consultation_id}/status", json={"status": "completed"},
                        headers=auth(doctor_token)).status_code == 200
    analytics = client.get("/admin/analytics", headers=auth(admin_token))
    assert analytics.status_code == 200 and analytics.json()["total_consultations"] == 1
    assert analytics.json()["demo_or_external_paid_minor"] == 75000
    assert client.get("/admin/audit-logs", headers=auth(patient_token)).status_code == 403
    assert client.get("/admin/audit-logs", headers=auth(admin_token)).status_code == 200
    saved = db.query(Prescription).first()
    assert "Herbal Medicine" not in saved.encrypted_document
    assert db.query(Consultation).count() == 1
    assert db.query(AuditLog).count() > 4


def test_cancellation_releases_slot_and_payment_is_void(client, db):
    doctor_token, _admin_token, doctor_id, _, _ = create_doctor_and_admin(client, db)
    p1 = register(client, "patient1@example.test")
    p2 = register(client, "patient2@example.test")
    slot_id, _ = add_slot(client, doctor_id, doctor_token)
    first = client.post("/bookings", json={"slot_id": slot_id},
                        headers={**auth(p1), "Idempotency-Key": "patient1-book"}).json()["id"]
    cancelled = client.patch(f"/consultations/{first}/status", json={"status": "cancelled"}, headers=auth(p1))
    assert cancelled.status_code == 200
    assert client.get(f"/consultations/{first}/payment", headers=auth(p1)).json()["status"] == "void"
    second = client.post("/bookings", json={"slot_id": slot_id},
                         headers={**auth(p2), "Idempotency-Key": "patient2-book"})
    assert second.status_code == 201, second.text
    assert second.json()["id"] != first
    assert len(client.get("/consultations", headers=auth(p1)).json()) == 1


def test_mfa_login_requires_second_factor_and_rejects_replay(client, monkeypatch):
    token = register(client, "mfa@example.test")
    secret, new_token = setup_mfa(client, token)
    login = client.post("/auth/login", json={"email": "mfa@example.test", "password": PASSWORD})
    assert login.json()["mfa_required"] is True
    challenge = login.json()["challenge_token"]
    assert client.get("/me", headers=auth(challenge)).status_code == 401
    assert client.get("/me", headers=auth(token)).status_code == 401
    assert client.get("/me", headers=auth(new_token)).status_code == 200
    current = int(security.time.time())
    monkeypatch.setattr(security.time, "time", lambda: current + 30)
    step = (current + 30) // 30
    verified = client.post("/auth/mfa/verify-login", json={"challenge_token": challenge,
                                                            "code": totp_for_step(secret, step)})
    assert verified.status_code == 200, verified.text
    assert client.get("/me", headers=auth(verified.json()["access_token"])).status_code == 200
    replay = client.post("/auth/mfa/verify-login", json={"challenge_token": challenge,
                                                          "code": totp_for_step(secret, step)})
    assert replay.status_code == 401


def test_input_validation_and_openapi(client):
    assert client.post("/auth/register", json={"email": "oops", "password": "short", "full_name": "Q"}).status_code == 422
    patient = register(client, "validation@example.test")
    assert client.post("/bookings", json={"slot_id": str(uuid.uuid4())},
                       headers=auth(patient)).status_code == 422  # no idempotency key
    spec = client.get("/openapi.json")
    assert spec.status_code == 200 and "/bookings" in spec.json()["paths"]
    assert client.get("/metrics").status_code == 403
    assert client.get("/metrics", headers={"Authorization": "Bearer test-metrics-token"}).status_code == 200


def test_admin_deactivation_revokes_tokens_and_prevents_self_disable(client, db):
    _, admin_token, _, _, _ = create_doctor_and_admin(client, db)
    patient_token = register(client, "disable@example.test")
    user_id = client.get("/me", headers=auth(patient_token)).json()["id"]
    assert client.get("/me", headers=auth(patient_token)).status_code == 200
    result = client.post(f"/admin/users/{user_id}/deactivate", headers=auth(admin_token))
    assert result.status_code == 200
    assert client.get("/me", headers=auth(patient_token)).status_code == 401
    assert client.post(f"/admin/users/{user_id}/deactivate", headers=auth(admin_token)).status_code == 200
    admin_id = client.get("/me", headers=auth(admin_token)).json()["id"]
    assert client.post(f"/admin/users/{admin_id}/deactivate", headers=auth(admin_token)).status_code == 409


def test_doctor_verification_and_blocking_own_slot(client, db):
    doctor_token, admin_token, doctor_id, _, _ = create_doctor_and_admin(client, db)
    slot_id, payload = add_slot(client, doctor_id, doctor_token)
    overlap = {
        "start_at": (datetime.fromisoformat(payload["start_at"]) + timedelta(minutes=15)).isoformat(),
        "end_at": (datetime.fromisoformat(payload["end_at"]) + timedelta(minutes=15)).isoformat(),
    }
    overlap_result = client.post(f"/doctors/{doctor_id}/slots", json=overlap,
                                 headers={**auth(doctor_token), "Idempotency-Key": "overlap-10001"})
    assert overlap_result.status_code == 409
    blocked = client.patch(f"/doctors/{doctor_id}/slots/{slot_id}/block", headers=auth(doctor_token))
    assert blocked.status_code == 200 and blocked.json()["status"] == "blocked"
    assert client.get(f"/doctors/{doctor_id}/slots").json() == []
    assert client.patch(f"/doctors/{doctor_id}/slots/{slot_id}/block",
                        headers=auth(doctor_token)).status_code == 200
    # A registered user promoted as unverified is not public until admin approval.
    register(client, "unverified@example.test")
    created = client.post("/admin/doctors", json={
        "user_email": "unverified@example.test", "license_no": "UNVERIFIED-2026-13",
        "specialty": "Yoga", "city": "Pune", "fee_minor": 8000, "verified": False},
        headers=auth(admin_token))
    assert created.status_code == 201
    unverified_id = created.json()["id"]
    assert client.get("/doctors", params={"specialty": "Yoga"}).json() == []
    assert client.post(f"/admin/doctors/{unverified_id}/verify", headers=auth(admin_token)).status_code == 200
    assert client.get("/doctors", params={"specialty": "Yoga"}).json()[0]["id"] == unverified_id


def test_paid_cancellation_marks_refund_pending_not_refunded(client, db):
    doctor_token, _, doctor_id, _, _ = create_doctor_and_admin(client, db)
    patient = register(client, "refund@example.test")
    slot_id, _ = add_slot(client, doctor_id, doctor_token)
    consult_id = client.post("/bookings", json={"slot_id": slot_id},
                             headers={**auth(patient), "Idempotency-Key": "refund-booking"}).json()["id"]
    payment_id = client.get(f"/consultations/{consult_id}/payment", headers=auth(patient)).json()["id"]
    assert client.post(f"/payments/{payment_id}/demo-settle",
                       headers={**auth(patient), "Idempotency-Key": "refund-demo-pay"}).status_code == 200
    assert client.patch(f"/consultations/{consult_id}/status", json={"status": "cancelled"},
                        headers=auth(patient)).status_code == 200
    assert client.get(f"/consultations/{consult_id}/payment", headers=auth(patient)).json()["status"] == "refund_pending"
