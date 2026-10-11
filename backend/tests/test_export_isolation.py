import io
import json
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.exports import runner
from app.ops import archive


def test_pdf_blocks_outbound_even_if_template_contains_external_assets(tmp_path, monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    html = (
        f'<html><style>@import url("{origin}/style");</style>'
        f'<script>fetch("{origin}/script")</script><img src="{origin}/image">'
        "<body><p>550.00</p></body></html>"
    )
    monkeypatch.setattr(runner, "html_document", lambda *_: html)
    source, output, target = [tmp_path / n for n in ("input.json", "output.json", "report.pdf")]
    source.write_text(
        json.dumps({"format": "pdf", "content": {}, "evidence": [], "target": str(target)})
    )
    monkeypatch.setattr(runner.sys, "argv", ["runner", str(source), str(output)])
    try:
        runner.main()
        assert json.loads(output.read_text()) == {}
        assert target.read_bytes().startswith(b"%PDF")
        assert requests == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "name,kind", [("../escape", "file"), ("safe", "link"), ("large", "oversize")]
)
def test_restore_archive_rejects_escape_links_and_size_limit(tmp_path, monkeypatch, name, kind):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        entry = tarfile.TarInfo(name)
        if kind == "link":
            entry.type = tarfile.SYMTYPE
            entry.linkname = "../escape"
        if kind == "oversize":
            entry.size = 21 * 1024**3
        tar.addfile(entry)
    stream.seek(0)
    monkeypatch.setattr(archive, "storage_root", lambda: tmp_path)
    monkeypatch.setattr(archive.sys, "stdin", SimpleNamespace(buffer=stream))
    monkeypatch.setattr(archive.sys, "argv", ["archive", "unpack"])
    with pytest.raises(ValueError):
        archive.main()
    assert not list(tmp_path.iterdir())
