import pytest
from sqlalchemy.orm import Session

from app.database.base import Base
from app.database.connection import engine, get_db
from app.models import User

TEST_USER_ID = 999999


@pytest.fixture
def db():
    """
    A session on the real database inside a transaction that is
    rolled back afterwards; commits in app code become savepoints.
    Skips the test if Postgres isn't reachable.
    """
    try:
        connection = engine.connect()
    except Exception as error:
        pytest.skip(f"database unavailable: {error}")

    transaction = connection.begin()
    # Tables the real DB hasn't been migrated to yet (Postgres DDL is
    # transactional, so this is rolled back with everything else).
    Base.metadata.create_all(bind=connection)
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    session.add(User(id=TEST_USER_ID, name="test", education="", skills="", preferences=""))
    session.commit()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db, monkeypatch):
    """API client whose requests use the rolled-back test session and user."""
    from fastapi.testclient import TestClient

    from app.main import app
    import app.api.tracking as tracking_api
    import app.api.task as task_api

    monkeypatch.setattr(tracking_api, "DEFAULT_USER_ID", TEST_USER_ID)
    monkeypatch.setattr(task_api, "DEFAULT_USER_ID", TEST_USER_ID)
    app.dependency_overrides[get_db] = lambda: db

    # No context manager: skips lifespan, so no startup recovery thread.
    yield TestClient(app)

    app.dependency_overrides.clear()
