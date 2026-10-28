import os
import uuid

os.environ["DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["RATE_LIMIT_BACKEND"] = "memory"
os.environ["JWT_SECRET"] = "test-only-fake-secret-xxxxxxxxxxxxxxxxxxxxxxxxxx"
os.environ["DATA_ENCRYPTION_KEYS"] = "SdZgE4RFx9oq4yV8cC3b-CUHtwyYN1ldWdaKtB80Fr4="
os.environ["METRICS_TOKEN"] = "test-metrics-token"
os.environ["PAYMENTS_MODE"] = "demo"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app import models  # noqa: F401

TEST_ENGINE = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False},
                            poolclass=StaticPool)
TestSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, expire_on_commit=False)


def override_db():
    with TestSession() as session:
        yield session


@pytest.fixture
def client():
    Base.metadata.create_all(bind=TEST_ENGINE)
    app.dependency_overrides[get_db] = override_db
    # Per-test IP address prevents unrelated tests hitting the per-IP auth rate limit.
    with TestClient(app, client=("test-" + uuid.uuid4().hex, 50000)) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def db():
    with TestSession() as session:
        yield session
