import io
import json
import uuid
import zipfile
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.db.models import (
    AuditEvent,
    DatasetVersion,
    ExportArtifact,
    ImportDraft,
    Upload,
    Workspace,
    now,
)
from app.exports.render import html_document, markdown_zip
from app.ingestion.storage import object_path
from app.jobs.queue import claim, finish
from app.jobs.worker import run_one
from app.reports.service import deterministic
from app.reports.tools import ToolRegistry
from tests.test_metrics import prepare_dataset
from tests.test_reports import context, create_report, finish_report


def sample(language="zh"):
    ctx = context()
    ctx["language"] = language
    registry = ToolRegistry(ctx, str(uuid.uuid4()), str(uuid.uuid4()))
    report = SimpleNamespace(
        id=registry.report_id,
        language=language,
        revision=1,
        title="安全验收 <script>alert(1)</script>",
        model_snapshot=None,
        metric_snapshot_id=uuid.uuid4(),
        rules=ctx["rules"],
    )
    data = SimpleNamespace(
        id=ctx["result"]["dataset_id"], fingerprint="fixture", cost_version_id=None, snapshot={}
    )
    content = deterministic(report, data, ctx, registry)
    content["products"][0]["product_name"] = (
        '恶意<img src="http://127.0.0.1/secret" onerror="alert(1)">'
    )
    return content, registry.evidence


def report_fixture(client):
    dataset = prepare_dataset(client)
    report = finish_report(client, create_report(client, dataset).json()["data"])
    return dataset, report


def test_offline_render_golden_and_injection():
    content, evidence = sample()
    html = html_document(content, evidence)
    assert "CNY 550.00" in html and "CNY 230.00" in html and "CNY 500.00" in html
    assert "<script" not in html and "<img" not in html and "font/ttf;base64" in html
    assert "default-src" in html and evidence[0]["evidence_id"] in html
    with zipfile.ZipFile(io.BytesIO(markdown_zip(content, evidence))) as archive:
        assert set(archive.namelist()) == {
            "report.md",
            "trend.svg",
            "contributions.svg",
            "evidence.json",
        }
        assert "<script" not in archive.read("report.md").decode()
        assert r"550\.00" in archive.read("report.md").decode()
        assert json.loads(archive.read("evidence.json")) == evidence


@pytest.mark.parametrize("fmt", ["html", "markdown", "pdf"])
def test_exports_durable_idempotent_download_expiry_and_isolation(
    api_client, db, isolated_storage, fmt
):
    dataset, report = report_fixture(api_client)
    path = f"/api/v1/reports/{report['id']}/exports"
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    response = api_client.post(path, headers=headers, json={"format": fmt})
    assert response.status_code == 202, response.text
    artifact = response.json()["data"]
    assert (
        api_client.post(path, headers=headers, json={"format": fmt}).json()["data"]["id"]
        == artifact["id"]
    )
    run_one()
    download = f"/api/v1/exports/{artifact['id']}/download"
    response = api_client.get(download)
    assert response.status_code == 200, response.text
    if fmt == "pdf":
        pdf = PdfReader(io.BytesIO(response.content))
        text = "".join(page.extract_text() for page in pdf.pages)
        assert "550.00" in text and "230.00" in text and "经营概览" in text
        assert all(page.get("/Resources").get("/Font") for page in pdf.pages)
    row = db.get(ExportArtifact, uuid.UUID(artifact["id"]))
    original_workspace = row.workspace_id
    foreign = Workspace(slug="foreign-export")
    db.add(foreign)
    db.flush()
    row.workspace_id = foreign.id
    db.commit()
    assert api_client.get(download).status_code == 404
    row.workspace_id = original_workspace
    row.expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert api_client.get(download).status_code == 410
    assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "export.created"))


def test_cancel_fences_old_worker_retry_bound_and_audit(api_client, db, workspace, make_job):
    job = make_job(workspace.id)
    claimed = claim()
    path = f"/api/v1/operations/jobs/{job.id}"
    assert api_client.post(path + "/cancel").json()["data"]["status"] == "cancelled"
    assert not finish(claimed, {"result": "stale"})
    assert api_client.post(path + "/retry").json()["data"]["status"] == "queued"
    retried = claim()
    assert finish(retried, {"result": "completed"})
    result = api_client.get(f"/api/v1/jobs/{job.id}").json()["data"]
    assert result["status"] == "succeeded" and result["result"] == {"result": "completed"}
    db.refresh(job)
    job.status = "failed"
    job.attempt = 3
    db.commit()
    assert api_client.post(path + "/retry").status_code == 409
    assert len(api_client.get("/api/v1/operations/audit").json()["data"]) == 2


def test_settings_revision_freezes_old_data_and_changes_new_import(
    api_client, db, isolated_storage
):
    dataset = prepare_dataset(api_client)
    frozen = api_client.get("/api/v1/datasets/" + dataset).json()["data"]["snapshot"]
    cfg = api_client.get("/api/v1/operations/settings").json()["data"]
    new = {
        **cfg,
        "timezone": "Asia/Singapore",
        "currency": "USD",
        "name": "测试店铺",
        "raw_retention_days": 7,
    }
    assert api_client.put("/api/v1/operations/settings", json=new).status_code == 200
    assert api_client.put("/api/v1/operations/settings", json=new).status_code == 409
    upload = db.scalar(select(Upload).where(Upload.kind == "orders"))
    draft = api_client.post(
        "/api/v1/imports", json={"upload_id": str(upload.id), "name": "新配置"}
    ).json()["data"]
    assert draft["config"]["options"]["currency"] == "USD"
    assert api_client.get("/api/v1/datasets/" + dataset).json()["data"]["snapshot"] == frozen


def test_cleanup_retains_normalized_data_and_requires_preview(api_client, db, isolated_storage):
    dataset, report = report_fixture(api_client)
    workspace = db.scalar(select(Workspace))
    workspace.raw_retention_days = 1
    for row in db.scalars(select(Upload)):
        row.created_at = now() - timedelta(days=2)
    db.commit()
    plan = api_client.get("/api/v1/operations/cleanup").json()["data"]
    assert plan["counts"]["sources"] == 2
    assert (
        api_client.post(
            "/api/v1/operations/cleanup", json={"token": "0" * 64, "confirmation": "确认删除"}
        ).status_code
        == 409
    )
    response = api_client.post(
        "/api/v1/operations/cleanup", json={"token": plan["token"], "confirmation": "确认删除"}
    )
    assert response.status_code == 200, response.text
    db.expire_all()
    for upload in db.scalars(select(Upload)):
        assert upload.source_deleted_at and not object_path(upload.storage_key).exists()
        assert not api_client.get("/api/v1/uploads/" + str(upload.id)).json()["data"][
            "source_available"
        ]
        assert (
            api_client.post(
                "/api/v1/imports", json={"upload_id": str(upload.id), "name": "失效"}
            ).status_code
            == 410
        )
    # A different query computes from normalized rows after original sources disappear.
    created = api_client.post(
        "/api/v1/reports",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "query": {
                **report["query"],
                "comparison": "none",
                "compare_start": None,
                "compare_end_exclusive": None,
            }
        },
    ).json()["data"]
    again = finish_report(api_client, created)
    assert again["content"]["metrics"]["current"]["metrics"]["net_sales"]["value"] == "55000"


@pytest.mark.parametrize("kind", ["report", "dataset", "cost", "upload"])
def test_deletion_impact_cascades_and_invalidates_links(api_client, db, isolated_storage, kind):
    dataset, report = report_fixture(api_client)
    artifact = api_client.post(
        f"/api/v1/reports/{report['id']}/exports",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"format": "markdown"},
    ).json()["data"]
    run_one()
    row = db.get(DatasetVersion, uuid.UUID(dataset))
    target = {
        "report": report["id"],
        "dataset": dataset,
        "cost": str(row.cost_version_id),
        "upload": str(db.get(ImportDraft, row.import_id).upload_id),
    }[kind]
    path = f"/api/v1/operations/deletion/{kind}/{target}"
    plan = api_client.get(path).json()["data"]
    assert plan["counts"]["reports"] == 1 and plan["counts"]["exports"] == 1
    response = api_client.post(path, json={"token": plan["token"], "confirmation": "确认删除"})
    assert response.status_code == 200, response.text
    assert api_client.get(f"/api/v1/reports/{report['id']}").status_code == 404
    assert api_client.get(f"/api/v1/exports/{artifact['id']}/download").status_code == 404
    assert api_client.post(f"/api/v1/operations/jobs/{artifact['job_id']}/retry").status_code == 410
    if kind == "report":
        assert api_client.get("/api/v1/datasets/" + dataset).status_code == 200


def test_destructive_operation_busy_and_changed_impact(api_client, db, isolated_storage):
    dataset, report = report_fixture(api_client)
    path = f"/api/v1/operations/deletion/dataset/{dataset}"
    plan = api_client.get(path).json()["data"]
    second = create_report(api_client, dataset).json()["data"]
    payload = {"token": plan["token"], "confirmation": "确认删除"}
    assert api_client.post(path, json=payload).status_code == 409
    finish_report(api_client, second)
    assert api_client.post(path, json=payload).status_code == 409


def test_audit_never_records_model_key(api_client, db):
    key = "synthetic-audit-secret-only"
    response = api_client.post(
        "/api/v1/model-configs",
        json={
            "name": "audit",
            "model_name": "demo",
            "base_url": "https://example.com/v1",
            "api_key": key,
            "consent": True,
        },
    )
    assert response.status_code == 201
    audit = api_client.get("/api/v1/operations/audit")
    assert key not in audit.text and "credential_ciphertext" not in audit.text
    assert audit.json()["data"][0]["details"]["credential_set"]


def test_operations_direct_access_and_origin(client):
    for path in ("settings", "status", "audit", "cleanup"):
        assert client.get("/api/v1/operations/" + path).status_code == 200
    response = client.post(
        "/api/v1/operations/cleanup",
        json={"token": "0" * 64, "confirmation": "确认删除"},
        headers={"Origin": "https://untrusted.example"},
    )
    assert response.status_code == 403


def test_cancel_during_model_call_keeps_core_and_rejects_late_output_A16(
    api_client, db, isolated_storage, monkeypatch
):
    from app.db.models import AgentRun
    from app.reports import service

    dataset = prepare_dataset(api_client)
    item = create_report(api_client, dataset).json()["data"]
    run_one()  # compute metric dependency
    job = claim()
    monkeypatch.setattr(service, "model_request", lambda *args: ({"key": "synthetic"}, None))

    def in_flight(request, timeout, cancelled, **kwargs):
        assert not cancelled()
        response = api_client.post(f"/api/v1/operations/jobs/{job.id}/cancel")
        assert response.status_code == 200
        assert cancelled()
        return {
            "analysis": None,
            "error_code": "TIMEOUT",
            "usage": {},
            "steps": [],
            "extra_evidence": [],
        }

    monkeypatch.setattr(service, "model_process", in_flight)
    service.execute(job)
    db.expire_all()
    report = api_client.get(f"/api/v1/reports/{item['id']}").json()["data"]
    assert report["job_status"] == "cancelled"
    assert report["content"]["model_error_code"] == "CANCELLED"
    assert report["content"]["metrics"]["current"]["metrics"]["net_sales"]["value"] == "55000"
    assert db.scalar(select(AgentRun).where(AgentRun.job_id == job.id)).error_code == "CANCELLED"


def test_offline_render_follows_report_language():
    content, evidence = sample("en")
    html = html_document(content, evidence)
    assert '<html lang="en">' in html and "<title>ShopPulse report</title>" in html
    for text in (
        "Overview",
        "Trend and sales contribution",
        "Products (top ten by net sales)",
        "Anomalies and limitations",
        "Net sales swing",
        "Heuristic swing alert",
        "Net sales in the current period: CNY 550.00.",
        "Evidence appendix",
    ):
        assert text in html, text
    for text in (
        "经营概览",
        "证据附录",
        "异常与限制",
        "冻结经营报告",
        "启发式",
        "未选择",
        "实际值",
    ):
        assert text not in html, text
    with zipfile.ZipFile(io.BytesIO(markdown_zip(content, evidence))) as archive:
        report = archive.read("report.md").decode()
        trend = archive.read("trend.svg").decode()
    assert "## Overview" in report and "## Evidence appendix" in report
    assert "Priority Medium · Effort Small · Verification metric Net sales" in report.replace(
        "\\", ""
    )
    assert "经营概览" not in report and "Net sales trend" in trend
    chinese = html_document(*sample())
    assert '<html lang="zh-CN">' in chinese and "经营概览" in chinese and "Overview" not in chinese
