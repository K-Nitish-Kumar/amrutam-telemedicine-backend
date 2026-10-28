"""One-time admin account bootstrap; reads secrets exclusively from environment."""
import argparse
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditLog, Profile, User
from app.security import hash_password


def main():
    parser = argparse.ArgumentParser(description="Create the initial administrator")
    parser.add_argument("--skip-existing", action="store_true", help="Succeed if the admin account already exists")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.admin_email or len(settings.admin_password) < 16:
        raise SystemExit("Set ADMIN_EMAIL and ADMIN_PASSWORD (min 16 chars) in .env")
    email = settings.admin_email.strip().lower()
    with SessionLocal.begin() as db:
        if db.scalar(select(User.id).where(User.email == email)):
            if args.skip_existing:
                print("Admin email already exists; account left unchanged.")
                return
            raise SystemExit("Admin email already exists. Bootstrap is create-only.")
        admin = User(email=email, password_hash=hash_password(settings.admin_password), role="admin")
        db.add(admin)
        db.flush()
        db.add(Profile(user_id=admin.id, full_name="Administrator"))
        db.add(AuditLog(actor_id=admin.id, action="admin.bootstrapped", entity_type="users",
                        entity_id=str(admin.id), meta={}))
    print("Admin account created. Log in, enroll MFA and confirm to unlock admin endpoints.")


if __name__ == "__main__":
    main()
