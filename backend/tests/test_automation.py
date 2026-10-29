import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import select

from app.automation import scheduler
from app.core.config import settings
from app.db.models import ActionItem, Report, ReportSchedule, now
from app.jobs.worker import run_one
from app.providers.credentials import rotate
from tests.test_metrics import prepare_dataset
from tests.test_reports import create_report, finish_report


@pytest.fixture
def webhook(monkeypatch):
    received = []

    class Hook(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            received.append({"path": self.path, "body": json.loads(self.rfile.read(size))})
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(settings(), "model_allowed_origins", [origin])
    yield origin, received
    server.shutdown()
    server.server_close()
    thread.join()


def test_next_run_uses_workspace_timezone():
    after = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)  # Monday 09:00 in Shanghai
    assert scheduler.next_run(0, 8, "Asia/Shanghai", after) == datetime(
        2026, 10, 12, 0, 0, tzinfo=UTC
    )
    assert scheduler.next_run(0, 10, "Asia/Shanghai", after) == datetime(
        2026, 10, 5, 2, 0, tzinfo=UTC
    )
    assert scheduler.next_run(6, 0, "UTC", after) == datetime(2026, 10, 11, 0, 0, tzinfo=UTC)


def test_merchant_notes_crud_and_report_context(api_client, isolated_storage):
    bad = {
        "start_date": "2026-10-05",
        "end_exclusive": "2026-10-01",
        "kind": "promotion",
        "text": "x",
    }
    assert api_client.post("/api/v1/notes", json=bad).status_code == 422
    note = api_client.post(
        "/api/v1/notes",
        json={
            "start_date": "2026-09-29",
            "end_exclusive": "2026-10-02",
            "kind": "promotion",
            "text": "国庆预热满减",
        },
    ).json()["data"]
    outside = api_client.post(
        "/api/v1/notes",
        json={"start_date": "2025-01-01", "end_exclusive": "2025-01-02", "text": "旧备注"},
    ).json()["data"]
    assert len(api_client.get("/api/v1/notes").json()["data"]) == 2
    dataset = prepare_dataset(api_client)
    report = finish_report(api_client, create_report(api_client, dataset).json()["data"])
    notes = report["content"]["merchant_notes"]
    assert [n["id"] for n in notes] == [note["id"]] and notes[0]["kind"] == "promotion"
    tools = [e["tool"] for e in report["content"]["evidence_index"]]
    assert "get_merchant_notes" in tools and len(tools) == 8
    updated = api_client.put(
        f"/api/v1/notes/{note['id']}",
        json={**{k: note[k] for k in ("start_date", "end_exclusive", "kind")}, "text": "已更新"},
    ).json()["data"]
    assert updated["text"] == "已更新"
    assert api_client.delete(f"/api/v1/notes/{outside['id']}").status_code == 204
    assert (
        api_client.post(
            "/api/v1/notes", json=bad, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_action_items_follow_up_and_evaluation(api_client, db, isolated_storage):
    dataset = prepare_dataset(api_client)
    first = api_client.post(
        "/api/v1/reports",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "title": "上周",
            "query": {
                "dataset_id": dataset,
                "start": "2026-09-21",
                "end_exclusive": "2026-09-28",
                "comparison": "none",
            },
        },
    ).json()["data"]
    finish_report(api_client, first)
    actions = api_client.get("/api/v1/actions").json()["data"]
    assert actions["total"] == 1 and actions["items"][0]["report_title"] == "上周"
    action = actions["items"][0]
    conflict = api_client.patch(
        f"/api/v1/actions/{action['id']}", json={"revision": 9, "status": "done"}
    )
    assert conflict.status_code == 409
    done = api_client.patch(
        f"/api/v1/actions/{action['id']}", json={"revision": 1, "status": "done", "note": "已核对"}
    ).json()["data"]
    assert done["status"] == "done" and done["note"] == "已核对" and done["revision"] == 2
    second = finish_report(api_client, create_report(api_client, dataset).json()["data"])
    followups = second["content"]["action_followups"]
    assert len(followups) == 1
    item = followups[0]
    assert item["action_id"] == action["id"] and item["verification_metric"] == "net_sales"
    assert item["state"] == "improved" and item["change_rate"] == "0.100000000000"
    assert item["baseline"]["value"] == "50000" and item["current"]["value"] == "55000"
    assert any(e["tool"] == "check_recommendation" for e in second["content"]["evidence_index"])
    row = db.get(ActionItem, uuid.UUID(action["id"]))
    db.refresh(row)
    assert row.evaluation["state"] == "improved" and row.evaluation["report_id"] == second["id"]
    api_client.patch(f"/api/v1/actions/{action['id']}", json={"revision": 2, "status": "dismissed"})
    third = finish_report(api_client, create_report(api_client, dataset).json()["data"])
    assert third["content"]["action_followups"] == []
    assert api_client.get("/api/v1/actions?status=dismissed").json()["data"]["total"] == 1


def test_schedule_lifecycle_runs_and_notifies(api_client, db, isolated_storage, webhook):
    origin, received = webhook
    prepare_dataset(api_client)
    invalid = api_client.post(
        "/api/v1/schedules", json={"name": "周报", "webhook_url": "https://user:pw@example.com/x"}
    )
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "INVALID_WEBHOOK_URL"
    created = api_client.post(
        "/api/v1/schedules",
        json={
            "name": "每周一",
            "title": "自动周报",
            "weekday": 0,
            "hour": 9,
            "webhook_url": origin + "/hook?token=secret-token",
            "webhook_format": "feishu",
        },
    )
    assert created.status_code == 201, created.text
    schedule = created.json()["data"]
    assert "secret-token" not in created.text and schedule["has_webhook"]
    assert schedule["next_period"] == {"start": "2026-09-28", "end_exclusive": "2026-10-05"}
    row = db.get(ReportSchedule, uuid.UUID(schedule["id"]))
    assert "secret-token" not in row.webhook_ciphertext
    assert scheduler.tick() == []  # Not due yet.
    row.next_run_at = now() - timedelta(minutes=1)
    db.commit()
    results = scheduler.tick()
    assert results[0]["status"] == "CREATED"
    report = finish_report(api_client, {"id": results[0]["report_id"]})
    assert report["schedule_id"] == schedule["id"]
    assert report["title"].startswith("自动周报 · 2026-09-28")
    assert report["query"]["start"] == "2026-09-28"
    run_one()  # notify_webhook job
    assert received and received[0]["path"] == "/hook?token=secret-token"
    body = received[0]["body"]
    assert body["msg_type"] == "text" and "CNY 550.00" in body["content"]["text"]
    detail = api_client.get("/api/v1/schedules").json()["data"][0]
    assert detail["last_status"] == "NOTIFIED" and detail["last_report_id"] == report["id"]
    db.expire_all()
    row = db.get(ReportSchedule, uuid.UUID(schedule["id"]))
    row.next_run_at = now() - timedelta(minutes=1)
    db.commit()
    assert scheduler.tick()[0]["status"] == "NO_NEW_DATA"
    manual = api_client.post(f"/api/v1/schedules/{schedule['id']}/run").json()["data"]
    assert manual["status"] == "CREATED"
    revision = db.get(Report, uuid.UUID(manual["report_id"]))
    assert revision.parent_id == uuid.UUID(report["id"]) and revision.revision == 2
    assert rotate(db, dry_run=True) == 0
    db.rollback()  # rotate() locks schedules; release them before the next API write.
    patched = api_client.patch(
        f"/api/v1/schedules/{schedule['id']}",
        json={"revision": schedule["revision"], "enabled": False, "clear_webhook": True},
    ).json()["data"]
    assert not patched["enabled"] and patched["next_run_at"] is None and not patched["has_webhook"]
    assert api_client.delete(f"/api/v1/schedules/{schedule['id']}").status_code == 204
    db.expire_all()
    assert db.get(Report, uuid.UUID(report["id"])).schedule_id is None


def test_schedule_without_dataset_and_model_reference(api_client, db, isolated_storage):
    schedule = api_client.post("/api/v1/schedules", json={"name": "空"}).json()["data"]
    assert schedule["next_period"] is None
    assert (
        api_client.post(f"/api/v1/schedules/{schedule['id']}/run").json()["data"]["status"]
        == "NO_DATASET"
    )
    config = api_client.post(
        "/api/v1/model-configs",
        json={
            "name": "m",
            "base_url": "https://provider.example/v1",
            "model_name": "full",
            "consent": True,
        },
    ).json()["data"]
    api_client.patch(
        f"/api/v1/schedules/{schedule['id']}",
        json={"revision": schedule["revision"], "model_config_id": config["id"]},
    )
    assert api_client.delete(f"/api/v1/model-configs/{config['id']}").status_code == 409
    assert db.scalar(select(ReportSchedule.last_status)) == "NO_DATASET"
