import json
import socket
import threading
import uuid
from datetime import timedelta
from http.server import ThreadingHTTPServer

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.db.models import Job, ModelConfig, Workspace, now
from app.jobs.queue import claim
from app.providers import egress, service
from app.providers.adapter import ProviderAdapter
from app.providers.credentials import decrypt, encrypt, rotate
from app.providers.egress import ProviderError, normalize_url, post, validate_target
from app.providers.mock_server import Handler, completion

KEY = "synthetic-key-never-a-real-credential"
INPUT = {
    "name": "测试配置",
    "base_url": "https://provider.example/v1/",
    "model_name": "full",
    "consent": True,
    "api_key": KEY,
}


@pytest.fixture
def provider(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(settings(), "model_allowed_origins", [origin])
    yield origin + "/v1"
    server.shutdown()
    server.server_close()
    thread.join()


def create(client, **overrides):
    response = client.post("/api/v1/model-configs", json={**INPUT, **overrides})
    assert response.status_code == 201, response.text
    assert KEY not in response.text and "credential_ciphertext" not in response.text
    return response.json()["data"]


def test_credentials_crud_revision_and_default(api_client, db):
    item = create(api_client, is_default=True)
    path = "/api/v1/model-configs/" + item["id"]
    record = db.get(ModelConfig, uuid.UUID(item["id"]))
    assert KEY not in record.credential_ciphertext and decrypt(record) == KEY
    before = record.credential_ciphertext
    payload = {k: v for k, v in INPUT.items() if k != "api_key"}
    changed = api_client.patch(path, json={**payload, "revision": 1}).json()["data"]
    assert changed["revision"] == 2 and changed["has_api_key"]
    db.refresh(record)
    assert before == record.credential_ciphertext
    assert api_client.patch(path, json={**payload, "revision": 1}).status_code == 409
    cleared = api_client.patch(path, json={**payload, "revision": 2, "clear_api_key": True})
    assert not cleared.json()["data"]["has_api_key"]
    assert (
        api_client.patch(path, json={**INPUT, "revision": 3, "clear_api_key": True}).status_code
        == 422
    )
    replacement = api_client.patch(
        path, json={**INPUT, "revision": 3, "api_key": KEY + "new", "is_default": True}
    )
    assert replacement.status_code == 200
    second = create(api_client, is_default=True)
    rows = api_client.get("/api/v1/model-configs").json()["data"]
    assert [row["id"] for row in rows if row["is_default"]] == [second["id"]]
    assert api_client.delete(path).status_code == 204
    assert api_client.delete(path).status_code == 404


def test_workspace_scope_and_input_redaction(api_client, client, db):
    item = create(api_client)
    path = "/api/v1/model-configs/" + item["id"]
    other = Workspace(slug="other")
    db.add(other)
    db.flush()
    record = db.get(ModelConfig, uuid.UUID(item["id"]))
    record.workspace_id = other.id
    db.commit()
    assert api_client.get("/api/v1/model-configs").json()["data"] == []
    assert api_client.delete(path).status_code == 404
    assert api_client.post(path + "/test").status_code == 404
    for patch in ({"api_key": KEY + "\n"}, {"api_key": None}, {"consent": False}, {"unknown": KEY}):
        response = api_client.post("/api/v1/model-configs", json={**INPUT, **patch})
        assert response.status_code == 422 and KEY not in response.text
    client.headers["Origin"] = "https://untrusted.example"
    assert client.post("/api/v1/model-configs", json=INPUT).status_code == 403


def test_rotation_authenticated_binding_and_rollback(api_client, db, tmp_path, monkeypatch):
    first = create(api_client)
    second = create(api_client)
    a = db.get(ModelConfig, uuid.UUID(first["id"]))
    b = db.get(ModelConfig, uuid.UUID(second["id"]))
    old = a.credential_ciphertext
    b.credential_ciphertext = old
    with pytest.raises(AppError):
        decrypt(b)
    encrypt(b, KEY)
    db.commit()
    new_key = tmp_path / "new_key"
    new_key.write_text("rotation-test-master-key-" * 3)
    monkeypatch.setattr(
        settings(), "credential_old_keys", {1: settings().credential_master_key_file}
    )
    monkeypatch.setattr(settings(), "credential_key_version", 2)
    monkeypatch.setattr(settings(), "credential_master_key_file", str(new_key))
    assert rotate(db, dry_run=True) == 2 and a.credential_ciphertext == old
    assert rotate(db) == 2
    db.commit()
    assert decrypt(a) == KEY and a.credential_key_version == 2
    assert a.credential_ciphertext != old
    monkeypatch.setattr(settings(), "credential_old_keys", {})
    assert decrypt(a) == KEY
    b.credential_ciphertext = old
    b.credential_key_version = 1
    db.commit()
    with pytest.raises(AppError):
        rotate(db)
    db.rollback()
    assert decrypt(a) == KEY


@pytest.mark.parametrize(
    "url",
    [
        "https://u:p@example.com/v1",
        "https://example.com/v1?key=x",
        "https://example.com/#x",
        "https://example.com/v1/chat/completions",
        "https://example.com/../v1",
        "https://example.com/%2e",
        "ftp://example.com/v1",
        "https://example.com\\@evil.com",
    ],
)
def test_bad_urls(url):
    with pytest.raises(ProviderError, match="INVALID_BASE_URL"):
        normalize_url(url)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.100.100.200",
        "::1",
        "::ffff:127.0.0.1",
        "fc00::1",
        "2002:7f00:1::",
        "64:ff9b::7f00:1",
    ],
)
def test_private_dns_and_metadata_blocked(ip, monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))],
    )
    with pytest.raises(ProviderError, match="EGRESS_BLOCKED"):
        validate_target("https://provider.example/v1")


def test_dns_rebinding_pinned_tls_and_mixed_answers(monkeypatch):
    calls, connected, tls = [], [], []

    def resolve(*args, **kwargs):
        calls.append(1)
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("8.8.8.8" if len(calls) == 1 else "127.0.0.1", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    addresses = validate_target("https://provider.example/v1")

    class Sock:
        def settimeout(self, value):
            pass

        def connect(self, address):
            connected.append(address)

        def close(self):
            pass

    class Context:
        def wrap_socket(self, sock, server_hostname):
            tls.append(server_hostname)
            return sock

    monkeypatch.setattr(socket, "socket", lambda *a: Sock())
    monkeypatch.setattr(egress.ssl, "create_default_context", lambda: Context())
    connection = egress.PinnedConnection("provider.example", 443, addresses[0], True, 5)
    connection.connect()
    assert connected == [("8.8.8.8", 443)] and calls == [1] and tls == ["provider.example"]
    with pytest.raises(ProviderError, match="EGRESS_BLOCKED"):
        validate_target("https://provider.example/v1")


@pytest.mark.parametrize(
    "model,strategy",
    [
        ("full", "native_tools"),
        ("no-tools", "restricted_json"),
        ("text-json", "restricted_json"),
        ("narrative", "narrative"),
    ],
)
def test_real_http_probe_modes(provider, model, strategy):
    result = service.probe({"base_url": provider, "model_name": model, "timeout_seconds": 5}, KEY)
    assert result["usable"] and result["strategy"] == strategy
    assert 1 <= result["requests"] <= 6
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize(
    "model,code",
    [
        ("auth-fail", "AUTH_FAILED"),
        ("missing", "MODEL_NOT_FOUND"),
        ("rate-limit", "RATE_LIMITED"),
        ("unavailable", "PROVIDER_UNAVAILABLE"),
        ("redirect", "REDIRECT_BLOCKED"),
        ("invalid", "INVALID_RESPONSE"),
    ],
)
def test_real_http_error_classes(provider, model, code):
    result = service.probe({"base_url": provider, "model_name": model, "timeout_seconds": 5}, KEY)
    assert not result["usable"] and result["stages"]["basic"]["code"] == code
    assert "Synthetic provider error" not in json.dumps(result)
    assert result["requests"] == (2 if model in {"rate-limit", "unavailable"} else 1)


def test_allowlist_is_exact_and_redirects_never_followed(provider, monkeypatch):
    assert post(provider, KEY, {"model": "full", "messages": [{"content": "OK"}]}, 5)
    monkeypatch.setattr(settings(), "model_allowed_origins", [])
    with pytest.raises(ProviderError, match="EGRESS_BLOCKED"):
        post(provider, KEY, {}, 5)


def test_probe_job_deduplicates_blocks_edits_and_redacts(api_client, db, provider):
    item = create(api_client, base_url=provider)
    path = "/api/v1/model-configs/" + item["id"]
    job_id = api_client.post(path + "/test").json()["data"]["job_id"]
    assert api_client.post(path + "/test").json()["data"]["job_id"] == job_id
    assert api_client.patch(path, json={**INPUT, "revision": 1}).status_code == 409
    assert api_client.delete(path).status_code == 409
    job = claim()
    assert job.payload == {"config_id": item["id"], "revision": 1}
    service.execute(job)
    response = api_client.get("/api/v1/jobs/" + job_id)
    assert response.json()["data"]["status"] == "succeeded"
    assert KEY not in response.text
    rows = api_client.get("/api/v1/model-configs").json()["data"]
    assert rows[0]["capabilities"]["native_tools"]
    assert (
        api_client.patch(path, json={**INPUT, "revision": 1}).json()["data"]["capabilities"] is None
    )


def test_stale_worker_cannot_commit(api_client, db, monkeypatch):
    item = create(api_client)
    api_client.post(f"/api/v1/model-configs/{item['id']}/test")
    job = claim()
    persisted = db.get(Job, job.id)
    persisted.lease_expires_at = now() - timedelta(seconds=1)
    db.commit()
    new_owner = claim()
    assert new_owner.lease_token > job.lease_token
    monkeypatch.setattr(service, "probe", lambda *a: {"usable": True, "strategy": "native_tools"})
    service.execute(job)
    db.expire_all()
    assert db.get(ModelConfig, uuid.UUID(item["id"])).capabilities is None
    assert db.get(Job, job.id).status == "running"


def test_unsupported_and_invalid_json_are_not_capabilities():
    sent = []

    def transport(url, key, payload, timeout, protocol="openai_chat"):
        sent.append(payload)
        return (
            completion('{"ok":1}') if "JSON" in payload["messages"][-1]["content"] else completion()
        )

    result = ProviderAdapter(
        {"base_url": "https://example.com", "model_name": "fake", "timeout_seconds": 5},
        KEY,
        transport,
    ).probe()
    assert result["usable"] and result["strategy"] == "narrative"
    assert not result["native_tools"] and not result["native_json"]
    assert set(sent[0]) == {"model", "messages"}


def test_credential_not_in_logs(api_client, capsys):
    create(api_client)
    api_client.post("/api/v1/model-configs", json={**INPUT, "api_key": KEY + "\r\n"})
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err


def test_partial_patch_preserves_unspecified_fields(api_client):
    item = create(api_client, is_default=True, timeout_seconds=20)
    path = f"/api/v1/model-configs/{item['id']}"
    result = api_client.patch(path, json={"revision": 1, "consent": True, "name": "改名"})
    assert result.status_code == 200
    changed = result.json()["data"]
    assert changed["has_api_key"] and changed["is_default"] and changed["timeout_seconds"] == 20
    assert changed["base_url"] == item["base_url"] and changed["revision"] == 2
    assert api_client.get(path).json()["data"]["name"] == "改名"
    assert (
        api_client.patch(path, json={"revision": 2, "consent": True, "api_key": None}).status_code
        == 422
    )


def test_mixed_dns_answers_and_nonstandard_port(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ["8.8.8.8", "10.0.0.1"]
        ],
    )
    with pytest.raises(ProviderError, match="EGRESS_BLOCKED"):
        validate_target("https://provider.example/v1")
    with pytest.raises(ProviderError, match="EGRESS_BLOCKED"):
        validate_target("https://provider.example:8443/v1")


def test_timeout_network_tls_and_oversized_response(monkeypatch):
    import ssl

    monkeypatch.setattr(egress, "validate_target", lambda url: [None])

    class Connection:
        def __init__(self, *args):
            pass

        def request(self, *args):
            raise TimeoutError()

        def close(self):
            pass

    monkeypatch.setattr(egress, "PinnedConnection", Connection)
    for exception, code in [
        (TimeoutError(), "TIMEOUT"),
        (OSError(), "NETWORK_ERROR"),
        (ssl.SSLError(), "TLS_FAILED"),
    ]:

        def request(*args, error=exception):
            raise error

        monkeypatch.setattr(Connection, "request", request)
        with pytest.raises(ProviderError, match=code):
            post("https://provider.example/v1", KEY, {}, 5)
    monkeypatch.setattr(Connection, "request", lambda *a: None)

    class Response:
        status = 200

        def read(self, size):
            return b" " * size

    monkeypatch.setattr(Connection, "getresponse", lambda self: Response(), raising=False)
    with pytest.raises(ProviderError, match="RESPONSE_TOO_LARGE"):
        post("https://provider.example/v1", KEY, {}, 5)


def test_process_deadline_kills_and_reaps(monkeypatch):
    import subprocess

    stopped = []

    class Process:
        def __init__(self, *args, **kwargs):
            assert KEY not in str(args) and "stderr" in kwargs

        def communicate(self, *args, **kwargs):
            if not stopped:
                raise subprocess.TimeoutExpired("probe", 90)
            return b"", b""

        def kill(self):
            stopped.append(True)

    monkeypatch.setattr(service.subprocess, "Popen", Process)
    with pytest.raises(ProviderError, match="TIMEOUT"):
        service.probe({}, KEY)
    assert stopped == [True]


def test_v1_consent_is_flagged_and_confirmed_without_new_revision(api_client, db):
    item = create(api_client)
    path = "/api/v1/model-configs/" + item["id"]
    assert item["consent_current"] and "question_text" in item["consent"]["fields"]
    row = db.get(ModelConfig, uuid.UUID(item["id"]))
    row.consent = {**row.consent, "version": "1.0", "fields": ["aggregate_metrics", "sku"]}
    row.capabilities = {"usable": True, "strategy": "native_tools"}
    db.commit()
    assert not api_client.get(path).json()["data"]["consent_current"]
    foreign = api_client.post(path + "/consent", headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403
    confirmed = api_client.post(path + "/consent")
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()["data"]
    assert data["consent_current"] and data["revision"] == item["revision"]
    assert {"question_text", "merchant_notes"} <= set(data["consent"]["fields"])
    assert data["consent"]["revision"] == data["revision"]
    assert data["capabilities"] == {"usable": True, "strategy": "native_tools"}
    assert KEY not in confirmed.text
