import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditLog, IdempotencyRecord, OutboxEvent


def audit(db: Session, actor_id: uuid.UUID | None, action: str, entity_type: str,
          entity_id: uuid.UUID | str, meta: dict | None = None) -> None:
    # Metadata must contain only a few non-sensitive enum / identifier fields.
    db.add(AuditLog(actor_id=actor_id, action=action, entity_type=entity_type,
                    entity_id=str(entity_id), meta=meta or {}))


def outbox(db: Session, event_type: str, payload: dict):
    db.add(OutboxEvent(event_type=event_type, payload=payload))


def utc_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def idempotency_replay(db: Session, actor: uuid.UUID, operation: str, key: str, payload: dict) -> tuple[uuid.UUID | None, str]:
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
    if db.bind.dialect.name == "postgresql":
        # Transaction-level lock also serializes concurrent retries BEFORE a record exists.
        advisory = int.from_bytes(hashlib.sha256(f"{actor}/{operation}/{key}".encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": advisory})
    rec = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.actor_id == actor,
                    IdempotencyRecord.operation == operation, IdempotencyRecord.request_key == key))
    if rec:
        if rec.payload_hash != fingerprint:
            raise HTTPException(status_code=409, detail="Idempotency key reused with different request")
        return uuid.UUID(rec.resource_id), fingerprint
    return None, fingerprint


def idempotency_save(db: Session, actor: uuid.UUID, operation: str, key: str,
                     fingerprint: str, resource_id: uuid.UUID):
    db.add(IdempotencyRecord(actor_id=actor, operation=operation, request_key=key,
                             payload_hash=fingerprint, resource_id=str(resource_id)))


def forbidden(message: str = "Not authorized for this resource"):
    raise HTTPException(status_code=403, detail=message)


def not_found(resource: str):
    raise HTTPException(status_code=404, detail=f"{resource} not found")
