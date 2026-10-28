"""DB transactional-outbox worker with crash-safe polling and exponential retries.

The default adapter reports events as processed in DEMO mode, not as actual emails/SMS.
Replace dispatch_event with your real notification provider and add a provider idempotency key.
"""
import json
import logging
import time
from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal
from app.models import OutboxEvent, utcnow

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("amrutam-worker")


def dispatch_event(event: OutboxEvent):
    # No sensitive information in event payloads; provider implementation is intentionally external.
    logger.info(json.dumps({"event": "outbox_demo_processed", "event_id": str(event.id),
                            "event_type": event.event_type}))


def process_batch(limit: int = 25) -> int:
    with SessionLocal.begin() as db:
        stmt = (select(OutboxEvent).where(OutboxEvent.processed_at.is_(None),
                                        OutboxEvent.available_at <= utcnow())
                .order_by(OutboxEvent.available_at).limit(limit).with_for_update(skip_locked=True))
        rows = db.scalars(stmt).all()
        for row in rows:
            try:
                dispatch_event(row)
                row.processed_at = utcnow()
            except Exception as exc:
                row.attempts += 1
                row.available_at = utcnow() + timedelta(seconds=min(3600, 2 ** min(row.attempts, 11)))
                row.last_error = type(exc).__name__  # no accidental PHI in stored exception text
        return len(rows)


def main():
    while True:
        try:
            count = process_batch()
        except Exception:
            logger.exception("worker_poll_failed")
            count = 0
        time.sleep(2 if count else 5)


if __name__ == "__main__":
    main()
