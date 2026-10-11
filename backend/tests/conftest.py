"""Tests use a random, isolated PostgreSQL schema; never clear application data."""

import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import session as session_module
from app.db.models import Base, Job, Workspace
from app.jobs import queue
from app.main import app


@pytest.fixture(scope="session")
def database():
    schema = "test_" + uuid.uuid4().hex
    admin = create_engine(settings().database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = create_engine(
        settings().database_url,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    patch = pytest.MonkeyPatch()
    patch.setattr(session_module, "engine", lambda: scoped)
    patch.setattr(queue, "engine", lambda: scoped)
    command.upgrade(Config("alembic.ini"), "head")
    command.check(Config("alembic.ini"))
    yield scoped
    scoped.dispose()
    patch.undo()
    with admin.connect() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


@pytest.fixture(autouse=True)
def clean(database):
    with database.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def db(database):
    with Session(database, expire_on_commit=False) as value:
        yield value


@pytest.fixture
def workspace(db):
    workspace = Workspace(name="Test workspace")
    db.add(workspace)
    db.flush()
    db.commit()
    return workspace


@pytest.fixture
def client():
    with TestClient(app) as client:
        client.headers["Origin"] = settings().origin
        yield client


@pytest.fixture
def api_client(client):
    return client


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "storage_root", str(tmp_path))


@pytest.fixture
def make_job(db):
    def create(workspace_id):
        job = Job(
            workspace_id=workspace_id,
            type="queue_test",
            payload={},
            request_hash=uuid.uuid4().hex,
            idempotency_key=uuid.uuid4().hex,
        )
        db.add(job)
        db.commit()
        return job

    return create
