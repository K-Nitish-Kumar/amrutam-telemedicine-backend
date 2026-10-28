"""Initial schema, constraints, and PostgreSQL overlap prevention.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-27
"""
from alembic import op
from app.db import Base
from app import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Model-driven initial migration; subsequent revisions should use explicit alter statements.
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        # Prevent overlapping slots even with simultaneous insertions on separate app replicas.
        op.execute("""ALTER TABLE availability_slots ADD CONSTRAINT ex_doctor_overlapping_slots
            EXCLUDE USING gist (doctor_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)""")
        op.execute("""CREATE FUNCTION prevent_audit_changes() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'audit logs are append-only'; END; $$""")
        op.execute("""CREATE TRIGGER trg_audit_immutable BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_changes()""")


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS prevent_audit_changes()")
        op.execute("DROP EXTENSION IF EXISTS btree_gist")
