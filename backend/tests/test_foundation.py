import io
import logging
import uuid
from datetime import timedelta

from sqlalchemy import select, text

from app.api.routes import SCHEMA_REVISION
from app.core.logging import SafeFormatter
from app.db.models import Job, Workspace, now
from app.jobs.queue import claim, finish, heartbeat
from app.jobs.worker import run_one


def test_health_and_request_id(client):
    response = client.get("/api/v1/health/ready", headers={"X-Request-ID": "bad-input"})
    assert response.status_code == 200
    assert uuid.UUID(response.headers["x-request-id"])
    assert response.json()["meta"]["request_id"] == response.headers["x-request-id"]
    assert client.get("/api/v1/health/live").status_code == 200


def test_readiness_rejects_wrong_migration_but_liveness_passes(client, db):
    db.execute(text("UPDATE alembic_version SET version_num='wrong'"))
    db.commit()
    try:
        assert client.get("/api/v1/health/ready").status_code == 503
        assert client.get("/api/v1/health/live").status_code == 200
    finally:
        db.execute(
            text("UPDATE alembic_version SET version_num=:version"), {"version": SCHEMA_REVISION}
        )
        db.commit()


def test_direct_access_initializes_one_workspace(client, db):
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import func

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.get("/api/v1/workspace"), range(4)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["data"]["id"] for r in responses}) == 1
    assert db.scalar(select(func.count()).select_from(Workspace)) == 1
    assert all("set-cookie" not in r.headers for r in responses)
    assert not any("/auth/" in path for path in client.get("/openapi.json").json()["paths"])
    tables = set(
        db.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname=current_schema()")
        ).scalars()
    )
    assert not {"users", "sessions", "login_limits"} & tables


def test_origin_and_validation_do_not_leak_input(client):
    for origin in ("https://untrusted.example", "null", ""):
        response = client.post(
            "/api/v1/reports",
            json={"query": {}},
            headers={"Origin": origin, "Idempotency-Key": "origin-check"},
        )
        assert response.status_code == 403
    secret_input = "should-never-be-returned"
    response = client.post(
        "/api/v1/reports",
        json={"query": {"dataset_id": secret_input}},
        headers={"Idempotency-Key": "invalid-input"},
    )
    assert response.status_code == 422 and secret_input not in response.text


def test_worker_rejects_unknown_job_type(db, workspace, make_job):
    job = make_job(workspace.id)
    assert run_one()
    db.refresh(job)
    assert job.status == "failed" and job.error_code == "UNKNOWN_JOB_TYPE"


def test_job_workspace_isolation(api_client, db, make_job):
    other = Workspace(slug="other", name="Other")
    db.add(other)
    db.commit()
    job = make_job(other.id)
    assert api_client.get(f"/api/v1/jobs/{job.id}").status_code == 404
    assert api_client.get("/api/v1/jobs").json()["data"] == []


def test_claim_lease_heartbeat_and_stale_results(db, workspace, make_job):
    submitted = make_job(workspace.id)
    old = claim()
    assert old.id == submitted.id
    assert claim() is None
    assert heartbeat(old)
    db.expire_all()
    job = db.get(Job, old.id)
    job.lease_expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert not finish(old, {"result": "stale"})
    current = claim()
    assert current.attempt == 2 and current.lease_token > old.lease_token
    assert not heartbeat(old)
    assert not finish(old, {"result": "stale"})
    assert finish(current, {"result": "current"})


def test_expired_final_attempt_is_failed(db, workspace, make_job):
    submitted = make_job(workspace.id)
    job = db.get(Job, submitted.id)
    job.status = "running"
    job.attempt = 3
    job.lease_expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert claim() is None
    db.refresh(job)
    assert job.status == "failed" and job.error_code == "LEASE_RETRIES_EXHAUSTED"


def test_logs_only_allow_structured_fields():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeFormatter())
    logger = logging.getLogger("test-safe-logger")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.info("api_key=%s", "must-not-appear", extra={"event": "provider_failed"})
    assert "must-not-appear" not in stream.getvalue()
    assert '"event": "provider_failed"' in stream.getvalue()
