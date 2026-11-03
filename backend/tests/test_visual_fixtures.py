"""Writes the API fixtures for the frontend's visual tests and component tests.

Skipped unless ``SHOPPULSE_WRITE_FIXTURES`` names the output file (normally
``frontend/src/test/api.json``). The data comes from the real API: the sample order and cost
files, a dashboard snapshot, two agent v3 reports from the mock model provider (the second
rechecks the first one's hypotheses), a follow-up question, an export, automation and
operations. IDs are replaced with stable ones so that regenerating gives a small diff.

    export SHOPPULSE_WRITE_FIXTURES=../frontend/src/test/api.json
    uv run pytest tests/test_visual_fixtures.py
"""

import json
import os
import re
import uuid
from pathlib import Path

import pytest

from app.jobs.worker import run_one
from tests.test_metrics import prepare_dataset, query
from tests.test_reports import ask, create_report, finish_report, model_config
from tests.test_reports import provider as mock_provider_fixture

provider = mock_provider_fixture
TARGET = os.environ.get("SHOPPULSE_WRITE_FIXTURES")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def stable_ids(text):
    seen = {}

    def replace(match):
        seen.setdefault(match.group(0), f"00000000-0000-4000-8000-{len(seen) + 1:012d}")
        return seen[match.group(0)]

    return UUID.sub(replace, text)


@pytest.mark.skipif(not TARGET, reason="set SHOPPULSE_WRITE_FIXTURES to write the fixtures")
def test_write_frontend_fixtures(api_client, db, isolated_storage, provider):
    fixtures = {}

    def get(path):
        response = api_client.get("/api/v1" + path)
        assert response.status_code == 200, (path, response.text)
        fixtures[path.split("?")[0]] = response.json()["data"]
        return response.json()["data"]

    dataset_id = prepare_dataset(api_client)
    get("/datasets")
    costs, drafts = get("/cost-versions"), get("/imports")
    get(f"/datasets/{dataset_id}")
    get(f"/cost-versions/{costs[0]['id']}")
    get(f"/datasets/{dataset_id}/skus")
    for draft in drafts:
        get(f"/imports/{draft['id']}")
        get(f"/imports/{draft['id']}/issues")
        get(f"/uploads/{draft['upload_id']}")

    snapshot = api_client.post(
        "/api/v1/metrics/query", json={**query(), "dataset_id": dataset_id}
    ).json()["data"]
    run_one()
    fixtures["/metrics/query"] = get(f"/metrics/{snapshot['id']}")
    get(f"/metrics/{snapshot['id']}/products")

    config = model_config(api_client, db, provider, "agent")
    assert api_client.post(f"/api/v1/model-configs/{config['id']}/test").status_code == 202
    run_one()
    first = finish_report(
        api_client, create_report(api_client, dataset_id, model_id=config["id"]).json()["data"]
    )
    revision = create_report(api_client, dataset_id, model_id=config["id"], parent_id=first["id"])
    second = finish_report(api_client, revision.json()["data"])
    assert second["content"]["hypothesis_recheck"] and second["content"]["history"]
    ask(api_client, second["id"], "这期毛利如何？")
    export = api_client.post(
        f"/api/v1/reports/{second['id']}/exports",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"format": "html"},
    )
    assert export.status_code == 202, export.text
    run_one()
    for report in (first, second):
        for suffix in ("", "/runs", "/actions", "/exports", "/messages"):
            get(f"/reports/{report['id']}{suffix}")
    for evidence in second["content"]["evidence_index"]:
        get(f"/reports/{second['id']}/evidence/{evidence['evidence_id']}")
    get("/reports")

    schedule = api_client.post(
        "/api/v1/schedules",
        json={"name": "每周一经营周报", "dataset_id": dataset_id, "model_config_id": config["id"]},
    )
    assert schedule.status_code == 201, schedule.text
    note = api_client.post(
        "/api/v1/notes",
        json={
            "start_date": "2026-09-28",
            "end_exclusive": "2026-10-05",
            "kind": "promotion",
            "text": "国庆促销：全店满 199 减 20。",
        },
    )
    assert note.status_code == 201, note.text
    for path in (
        "/workspace",
        "/model-configs",
        "/schedules",
        "/notes",
        "/actions?status=open",
        "/operations/settings",
        "/operations/status",
        "/operations/audit",
        "/jobs",
    ):
        get(path)

    text = json.dumps(fixtures, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    text = text.replace(provider.removesuffix("/v1"), "http://mock-provider:8099")
    Path(TARGET).write_text(stable_ids(text), encoding="utf-8", newline="\n")
